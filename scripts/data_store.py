"""큰 데이터 파일 = GitHub Release 자산 (repo-size-stage1, 2026-10-21 · 겸이 승인 1단계 '더 안 커지게').

매일 통째로 다시 쓰는 parquet 를 git 커밋 대신 릴리스 `data-latest` 의 자산(파일당 1개, 덮어쓰기)으로 둔다.
git 이력은 그대로(재작성 없음) — 앞으로의 증가만 멈춘다.

  python scripts/data_store.py pull  [--groups all|fin,prices,...] [--tag data-latest] [--dest DIR]
  python scripts/data_store.py push  --groups fin [--force]            # 워크플로 '저장' 단계(commit 조건과 같은 if)
  python scripts/data_store.py snapshot [--keep 8]                      # 주 1회 data-YYYYMMDD 보존(복기·감사용)
  python scripts/data_store.py status                                   # 원격 자산 목록 vs 로컬

원칙
- pull: 자산 다운로드 → sha256 확인 → 원래 경로. 실패(3회) 시 폴백 순서 = 로컬에 이미 있음 → 최신 주간 스냅샷
  data-YYYYMMDD → git 의 마지막 커밋본(manifest `git_rev`, 얕은 checkout 이면 그 커밋만 fetch). 폴백은
  data/data_store_status.json(추적 밖) + ::warning:: + 단계 요약, `--record-stale` 이면 reports/freshness.json stale 에도
  (조용한 대체 금지, LOOP.md).
- push: 같은 이름 덮어쓰기 = 임시 이름 업로드 → 기존 삭제 → 이름 변경(빈 창을 최소화). 막는 경우(--force 로만 통과):
  ① 원격과 같은 sha → 건너뜀, ② asof(최대 date) 가 원격보다 과거(역행), ③ 행 수 또는 크기가 원격의 절반 미만(빈 실행),
  ④ 이번 실행의 pull 이 그 파일을 폴백으로 받았음(옛 판 위에 증분한 결과로 새 판을 덮지 않게).
- 메타(sha256·크기·행 수·asof)는 자산 label 에 싣고(원격이 진실), 커밋용 사본은 data/data_store_manifest.json(작음).
- 표준 라이브러리만 사용(pick·us_accum 러너는 requirements 를 다 깔지 않음). 행 수·asof 는 polars/pyarrow 가 있으면만.
- 토큰: GH_TOKEN 또는 GITHUB_TOKEN (워크플로 permissions contents: write). 저장소: GITHUB_REPOSITORY 또는 origin URL.
롤백: 워크플로에서 data_store 단계를 빼고 .gitignore 의 '릴리스 자산' 블록을 지운 뒤 파일을 다시 git add.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
TAG = "data-latest"
SNAP_RE = re.compile(r"^data-(\d{8})$")
MANIFEST = ROOT / "data" / "data_store_manifest.json"
# 상태 파일은 git 추적 밖(data/* 무시) — 추적 파일을 더럽히면 커밋하지 않는 워크플로의 pull --rebase 가 막힌다.
STATUS = ROOT / "data" / "data_store_status.json"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"

# 그룹 = 같은 워크플로가 함께 쓰는 파일들. 경로는 glob 가능(연도별 파일).
GROUPS: dict[str, list[str]] = {
    "fin": ["data/fin/multi.parquet", "data/fin/full.parquet"],           # fin.yml
    "prices": ["data/kr_prices.parquet"],                                 # screener.yml (KR)
    "signals": ["data/signals.parquet"],                                  # screener.yml · briefing.yml
    "hist": ["data/hist/*_daily.parquet"],                                # hist.yml (연도별 kr_/us_YYYY 는 불변 → git 유지)
    "flows": ["data/flows/kr_inv_*.parquet"],                             # accum.yml
}


# ── 이름·메타 ────────────────────────────────────────────────────────
def asset_name(path: str) -> str:
    return path.replace("/", "__")


def asset_path(name: str) -> str:
    return name.replace("__", "/")


def patterns(groups: str | list[str]) -> list[str]:
    gs = list(GROUPS) if groups in ("all", ["all"], None, "") else (groups.split(",") if isinstance(groups, str) else groups)
    bad = [g for g in gs if g not in GROUPS]
    if bad:
        raise SystemExit(f"알 수 없는 그룹: {bad} (가능: {', '.join(GROUPS)})")
    return [p for g in gs for p in GROUPS[g]]


def matches(path: str, pats: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in pats)


def local_files(pats: list[str], root: Path | None = None) -> list[str]:
    root = root or ROOT
    out = set()
    for p in pats:
        out |= {str(f.relative_to(root)) for f in root.glob(p) if f.is_file()}
    return sorted(out)


def sha256(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def table_meta(fp: Path) -> dict:
    """행 수·asof(date 열 최댓값). 라이브러리가 없거나 읽기 실패면 빈 값."""
    try:
        import polars as pl  # noqa: PLC0415
        lf = pl.scan_parquet(fp)
        cols = lf.collect_schema().names()
        out = {"rows": int(lf.select(pl.len()).collect().item())}
        if "date" in cols:
            v = lf.select(pl.col("date").max()).collect().item()
            out["asof"] = str(v)[:10] if v is not None else None
        return out
    except Exception:  # noqa: BLE001
        pass
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415
        return {"rows": int(pq.ParquetFile(fp).metadata.num_rows)}
    except Exception:  # noqa: BLE001
        return {}


def file_meta(fp: Path) -> dict:
    return {"sha256": sha256(fp), "size": fp.stat().st_size, **table_meta(fp)}


def to_label(m: dict) -> str:
    return ";".join(f"{k}={m[k]}" for k in ("sha256", "size", "rows", "asof") if m.get(k) is not None)


def from_label(s: str | None) -> dict:
    out: dict = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = int(v) if k in ("size", "rows") and v.isdigit() else v
    return out


# ── GitHub REST (표준 라이브러리) ─────────────────────────────────────
class GH:
    def __init__(self, repo: str | None = None, token: str | None = None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY") or _origin_repo()
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""

    def _req(self, method: str, url: str, data: bytes | None = None, ctype: str | None = None,
             accept: str = "application/vnd.github+json", auth: bool = True, timeout: int = 300):
        h = {"Accept": accept, "User-Agent": "market-screener-data-store", "X-GitHub-Api-Version": "2022-11-28"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if ctype:
            h["Content-Type"] = ctype
        return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=timeout)

    def json(self, method: str, path: str, body: dict | None = None):
        url = path if path.startswith("http") else f"{API}/repos/{self.repo}{path}"
        data = json.dumps(body).encode() if body is not None else None
        with self._req(method, url, data, "application/json" if data else None) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def release(self, tag: str) -> dict | None:
        try:
            return self.json("GET", f"/releases/tags/{urllib.parse.quote(tag)}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def ensure_release(self, tag: str, body: str) -> dict:
        rel = self.release(tag)
        if rel:
            return rel
        return self.json("POST", "/releases", {"tag_name": tag, "target_commitish": "main", "name": tag, "body": body,
                                               "prerelease": True, "make_latest": "false"})

    def assets(self, rel: dict) -> list[dict]:
        out, page = [], 1
        while True:
            got = self.json("GET", f"/releases/{rel['id']}/assets?per_page=100&page={page}") or []
            out += got
            if len(got) < 100:
                return out
            page += 1

    def releases(self) -> list[dict]:
        out, page = [], 1
        while True:
            got = self.json("GET", f"/releases?per_page=100&page={page}") or []
            out += got
            if len(got) < 100:
                return out
            page += 1

    def download(self, asset: dict, dest: Path) -> None:
        """API 자산 URL → 302 → 서명 URL(인증 헤더 없이). 공개 저장소면 browser_download_url 로도 된다."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        h = {"Accept": "application/octet-stream", "User-Agent": "market-screener-data-store"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        opener = urllib.request.build_opener(NoRedirect)
        try:
            r = opener.open(urllib.request.Request(asset["url"], headers=h), timeout=300)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            r = urllib.request.urlopen(urllib.request.Request(e.headers["Location"], headers={"User-Agent": h["User-Agent"]}),
                                       timeout=300)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with r, open(dest, "wb") as f:
            while b := r.read(1 << 20):
                f.write(b)

    def upload(self, rel: dict, name: str, fp: Path, label: str) -> dict:
        q = urllib.parse.urlencode({"name": name, "label": label})
        with self._req("POST", f"{UPLOADS}/repos/{self.repo}/releases/{rel['id']}/assets?{q}", fp.read_bytes(),
                       "application/octet-stream", timeout=600) as r:
            return json.loads(r.read())

    def delete_asset(self, aid: int) -> None:
        self.json("DELETE", f"/releases/assets/{aid}")

    def rename_asset(self, aid: int, name: str, label: str) -> dict:
        return self.json("PATCH", f"/releases/assets/{aid}", {"name": name, "label": label})


def _origin_repo() -> str:
    try:
        url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout
        m = re.search(r"github\.com[:/]([^/]+/[^/.\s]+)", url)
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        return ""


# ── manifest·status ─────────────────────────────────────────────────
def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"tag": TAG, "files": {}}


def save_manifest(m: dict) -> None:
    """파일 한 줄 = 항목 하나 (워크플로끼리 rebase 병합이 줄 단위로 되게)."""
    doc = ("큰 데이터 파일의 릴리스 자산 메타(커밋용 사본 — 진실은 릴리스 자산 label). scripts/data_store.py 참조. "
           "git_rev = 이 파일이 git 에 마지막으로 있던 커밋(최후 폴백).")
    lines = ["{", f'  "_doc": {json.dumps(doc, ensure_ascii=False)},', f'  "tag": {json.dumps(m.get("tag", TAG))},', '  "files": {']
    items = sorted((m.get("files") or {}).items())
    for i, (k, v) in enumerate(items):
        lines.append(f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}" + ("," if i < len(items) - 1 else ""))
    lines += ["  }", "}"]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_status(op: str, rows: list[dict], extra: dict | None = None) -> dict:
    try:
        cur = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    except Exception:  # noqa: BLE001
        cur = {}
    bad = {"failed", "fallback_snapshot", "fallback_git", "fallback_local", "missing",
           "blocked_regress", "blocked_shrink", "blocked_pull_fallback"}
    cur[op] = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "run": os.environ.get("GITHUB_RUN_ID") or "local",
               "workflow": os.environ.get("GITHUB_WORKFLOW") or "", "ok": not any(r["status"] in bad for r in rows),
               "files": rows, **(extra or {})}
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write(f"\n### data_store {op}\n| 파일 | 상태 | 비고 |\n|---|---|---|\n")
            for r in rows:
                f.write(f"| {r['path']} | {r['status']} | {r.get('detail', '')} |\n")
    return cur[op]


def _warn(msg: str, level: str = "warning") -> None:
    print(f"::{level}::data_store {msg}" if os.environ.get("GITHUB_ACTIONS") else f"[{level}] {msg}", flush=True)


def _record_stale(path: str, what: str, got) -> None:
    try:
        sys.path.insert(0, str(ROOT))
        from screener import guard  # noqa: PLC0415
        guard.record_stale(path, what, "release:" + TAG, got)
    except Exception:  # noqa: BLE001
        pass


# ── pull ────────────────────────────────────────────────────────────
def _git_fallback(path: str, rev: str | None, dest: Path) -> bool:
    if not rev:
        return False
    def show() -> bytes | None:
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"], capture_output=True)
        return r.stdout if r.returncode == 0 and r.stdout else None
    blob = show()
    if blob is None:
        subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "--depth=1", "origin", rev], capture_output=True)
        blob = show()
    if blob is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return True


def _fetch(gh: GH, asset: dict, dest: Path, tries: int = 3) -> str | None:
    """받아서 label sha 와 맞으면 None, 아니면 오류 문자열."""
    want = from_label(asset.get("label")).get("sha256") or str(asset.get("digest") or "").removeprefix("sha256:") or None
    err = None
    for i in range(tries):
        tmp = dest.with_name(dest.name + ".part")
        try:
            gh.download(asset, tmp)
            got = sha256(tmp)
            if want and got != want:
                raise ValueError(f"sha 불일치 {got[:12]} ≠ {want[:12]}")
            os.replace(tmp, dest)
            return None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            tmp.unlink(missing_ok=True)
            time.sleep(2 * (i + 1))
    return err


def pull(groups="all", tag: str = TAG, dest_root: Path | None = None, gh: GH | None = None,
         record_stale: bool = False) -> dict:
    gh = gh or GH()
    pats = patterns(groups)
    man = load_manifest()
    root = dest_root or ROOT
    rows: list[dict] = []
    remote: dict[str, dict] = {}
    err = None
    try:
        rel = gh.release(tag)
        if rel is None:
            err = f"릴리스 {tag} 없음"
        else:
            remote = {asset_path(a["name"]): a for a in gh.assets(rel) if matches(asset_path(a["name"]), pats)}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    want = sorted(set(remote) | {p for p in (man.get("files") or {}) if matches(p, pats)})
    snap_cache: dict = {}
    for path in want:
        dest = root / path
        a = remote.get(path)
        if a is not None:
            meta = from_label(a.get("label"))
            if dest.exists() and meta.get("sha256") and sha256(dest) == meta["sha256"]:
                rows.append({"path": path, "status": "same", "asof": meta.get("asof")})
                continue
            e = _fetch(gh, a, dest)
            if e is None:
                rows.append({"path": path, "status": "ok", "asof": meta.get("asof"), "size": a.get("size")})
                continue
            reason = e
        else:
            reason = err or "원격 자산 없음"
        # 폴백: 로컬 → 최신 주간 스냅샷 → git 마지막 커밋본
        if dest_root is None and dest.exists():
            st, detail = "fallback_local", f"{reason} → 로컬 파일 유지"
        elif dest_root is None and (snap := _latest_snapshot_asset(gh, path, snap_cache)) and _fetch(gh, snap[1], dest) is None:
            st, detail = "fallback_snapshot", f"{reason} → {snap[0]}"
        elif _git_fallback(path, (man.get("files") or {}).get(path, {}).get("git_rev"), dest):
            st, detail = "fallback_git", f"{reason} → git {(man['files'][path]['git_rev'])[:8]}"
        else:
            st, detail = "missing", reason
        rows.append({"path": path, "status": st, "detail": detail})
        _warn(f"pull {path}: {st} — {detail}")
        if dest_root is None and record_stale:
            _record_stale(path, f"data_store pull {st}", detail)
    if not want and err:
        _warn(f"pull: {err}")
    out = write_status("pull", rows, {"tag": tag, "groups": groups if isinstance(groups, str) else ",".join(groups)}) \
        if dest_root is None else {"files": rows}
    for r in rows:
        print(f"pull {r['status']:<18} {r['path']} {r.get('detail', '')}")
    return out


def _latest_snapshot_asset(gh: GH, path: str, cache: dict) -> tuple[str, dict] | None:
    try:
        if "snap" not in cache:
            snaps = sorted((r for r in gh.releases() if SNAP_RE.match(r.get("tag_name", ""))), key=lambda r: r["tag_name"])
            cache["snap"] = snaps[-1] if snaps else None
            cache["assets"] = {asset_path(a["name"]): a for a in gh.assets(snaps[-1])} if snaps else {}
        a = cache["assets"].get(path)
        return (cache["snap"]["tag_name"], a) if a else None
    except Exception:  # noqa: BLE001
        return None


# ── push ────────────────────────────────────────────────────────────
def _pulled_fallback() -> set[str]:
    try:
        st = json.loads(STATUS.read_text(encoding="utf-8")).get("pull") or {}
        if st.get("run") != (os.environ.get("GITHUB_RUN_ID") or "local"):
            return set()
        return {r["path"] for r in st.get("files", []) if r["status"].startswith("fallback") or r["status"] == "missing"}
    except Exception:  # noqa: BLE001
        return set()


def upload_replace(gh: GH, rel: dict, assets: dict[str, dict], path: str, fp: Path, label: str) -> dict:
    """같은 이름 덮어쓰기: 임시 이름으로 올린 뒤 기존 삭제 → 이름 변경 (빈 창 최소화)."""
    name = asset_name(path)
    tmpname = name + ".uploading"
    if tmpname in assets:
        gh.delete_asset(assets[tmpname]["id"])
    new = gh.upload(rel, tmpname, fp, label)
    if name in assets:
        gh.delete_asset(assets[name]["id"])
    return gh.rename_asset(new["id"], name, label)


def push(groups, tag: str = TAG, force: bool = False, git_rev: str | None = None, gh: GH | None = None,
         body: str = "") -> dict:
    gh = gh or GH()
    pats = patterns(groups)
    man = load_manifest()
    man.setdefault("files", {})
    rows: list[dict] = []
    rel = gh.ensure_release(tag, body or "큰 데이터 파일 저장소(덮어쓰기). scripts/data_store.py — 이력 없음, 주간 스냅샷은 data-YYYYMMDD.")
    assets = {a["name"]: a for a in gh.assets(rel)}
    fell_back = _pulled_fallback()
    for path in local_files(pats):
        fp = ROOT / path
        m = file_meta(fp)
        r = assets.get(asset_name(path))
        rm = from_label(r.get("label")) if r else {}
        row = {"path": path, "size": m["size"], "asof": m.get("asof"), "rows": m.get("rows")}
        if r and rm.get("sha256") == m["sha256"]:
            rows.append({**row, "status": "unchanged"})
        elif not force and r and path in fell_back:
            rows.append({**row, "status": "blocked_pull_fallback", "detail": "이번 실행 pull 이 폴백 — 새 판 위에 쓴 게 아님"})
        elif not force and r and m.get("asof") and rm.get("asof") and m["asof"] < rm["asof"]:
            rows.append({**row, "status": "blocked_regress", "detail": f"asof {m['asof']} < 원격 {rm['asof']}"})
        elif not force and r and ((m.get("rows") is not None and rm.get("rows") and m["rows"] < rm["rows"] * 0.5)
                                  or m["size"] < int(rm.get("size") or r.get("size") or 0) * 0.5):
            rows.append({**row, "status": "blocked_shrink",
                         "detail": f"rows {m.get('rows')}/{rm.get('rows')} size {m['size']}/{rm.get('size') or r.get('size')}"})
        else:
            try:
                upload_replace(gh, rel, assets, path, fp, to_label(m))
                rows.append({**row, "status": "uploaded"})
            except Exception as e:  # noqa: BLE001
                rows.append({**row, "status": "failed", "detail": f"{type(e).__name__}: {e}"})
        st = rows[-1]["status"]
        if st in ("uploaded", "unchanged"):
            ent = man["files"].get(path, {})
            ent.update({k: m.get(k) for k in ("sha256", "size", "rows", "asof")})
            if st == "uploaded":
                ent["uploaded_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
            if git_rev:
                ent["git_rev"] = git_rev
            man["files"][path] = {k: v for k, v in ent.items() if v is not None}
        else:
            _warn(f"push {path}: {st} — {rows[-1].get('detail', '')}", "error" if st == "failed" else "warning")
    man["tag"] = tag
    save_manifest(man)
    out = write_status("push", rows, {"tag": tag})
    for r in rows:
        print(f"push {r['status']:<22} {r['path']} {r.get('detail', '')}")
    return out


# ── snapshot ────────────────────────────────────────────────────────
def snapshot(keep: int = 8, day: str | None = None, gh: GH | None = None) -> dict:
    """현재 로컬 파일(pull 직후)을 data-YYYYMMDD 릴리스로 보존, 최근 keep 개만 남김."""
    gh = gh or GH()
    day = day or datetime.now(KST).strftime("%Y%m%d")
    tag = f"data-{day}"
    rel = gh.ensure_release(tag, f"주간 데이터 스냅샷 {day} (복기·감사용, 최근 {keep}개 보존). 복원: "
                                 f"python scripts/data_store.py pull --tag {tag} [--dest DIR]")
    assets = {a["name"]: a for a in gh.assets(rel)}
    rows = []
    fell_back = _pulled_fallback()
    for path in local_files(patterns("all")):
        fp = ROOT / path
        if path in fell_back:                       # 폴백으로 받은 옛 판을 '그 주 값'으로 보존하지 않는다
            rows.append({"path": path, "status": "skipped_pull_fallback"})
            _warn(f"snapshot {path}: 이번 실행 pull 이 폴백 — 보존 안 함")
            continue
        m = file_meta(fp)
        old = assets.get(asset_name(path))
        if old and from_label(old.get("label")).get("sha256") == m["sha256"]:
            rows.append({"path": path, "status": "unchanged"})
            continue
        try:
            upload_replace(gh, rel, assets, path, fp, to_label(m))
            rows.append({"path": path, "status": "uploaded", "asof": m.get("asof")})
        except Exception as e:  # noqa: BLE001
            rows.append({"path": path, "status": "failed", "detail": f"{type(e).__name__}: {e}"})
            _warn(f"snapshot {path}: {e}", "error")
    pruned = prune_snapshots(gh, keep)
    out = write_status("snapshot", rows, {"tag": tag, "pruned": pruned})
    print(f"snapshot {tag}: {sum(r['status'] == 'uploaded' for r in rows)} uploaded, pruned {pruned}")
    return out


def prune_snapshots(gh: GH, keep: int) -> list[str]:
    snaps = sorted((r for r in gh.releases() if SNAP_RE.match(r.get("tag_name", ""))), key=lambda r: r["tag_name"])
    gone = []
    for r in snaps[:-keep] if keep > 0 else []:
        gh.json("DELETE", f"/releases/{r['id']}")
        try:
            gh.json("DELETE", f"/git/refs/tags/{r['tag_name']}")
        except urllib.error.HTTPError:
            pass
        gone.append(r["tag_name"])
    return gone


def status(tag: str = TAG, gh: GH | None = None) -> None:
    gh = gh or GH()
    rel = gh.release(tag)
    if not rel:
        print(f"릴리스 {tag} 없음")
        return
    for a in gh.assets(rel):
        m = from_label(a.get("label"))
        p = asset_path(a["name"])
        lp = ROOT / p
        same = lp.exists() and m.get("sha256") == sha256(lp)
        print(f"{p:<40} {a['size'] / 1e6:7.2f}MB asof={m.get('asof', '-'):<10} rows={m.get('rows', '-')} "
              f"updated={a['updated_at']} local={'same' if same else ('diff' if lp.exists() else 'none')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["pull", "push", "snapshot", "status"])
    ap.add_argument("--groups", default="all", help=f"쉼표 구분: {', '.join(GROUPS)} 또는 all")
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--dest", help="pull: 원래 경로 대신 이 폴더 아래로(복기용 — 작업 트리 안 건드림)")
    ap.add_argument("--record-stale", action="store_true",
                    help="pull: 폴백을 reports/freshness.json stale 에도 기록(reports 를 커밋하는 워크플로만 — 추적 파일을 바꾸므로)")
    ap.add_argument("--force", action="store_true", help="push: 역행·축소·폴백 차단 무시")
    ap.add_argument("--git-rev", help="push: manifest 에 최후 폴백 커밋 기록(최초 이전 때)")
    ap.add_argument("--keep", type=int, default=8)
    ap.add_argument("--day", help="snapshot: YYYYMMDD (기본 오늘 KST)")
    a = ap.parse_args(argv)
    if a.cmd == "pull":
        pull(a.groups, a.tag, Path(a.dest).resolve() if a.dest else None, record_stale=a.record_stale)
        return 0                                    # fail-open: 폴백·경고만, 실행은 계속
    if a.cmd == "push":
        res = push(a.groups, a.tag, a.force, a.git_rev)
        return 1 if any(r["status"] == "failed" for r in res["files"]) else 0
    if a.cmd == "snapshot":
        res = snapshot(a.keep, a.day)
        return 1 if any(r["status"] == "failed" for r in res["files"]) else 0
    status(a.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
