"""scripts/data_store.py — 릴리스 자산 저장·복원 (repo-size-stage1). 네트워크 없이 가짜 GH 로 검사."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import data_store as ds  # noqa: E402


class FakeGH:
    """릴리스·자산을 메모리에 두는 가짜 GitHub."""

    def __init__(self):
        self.rels: dict[str, dict] = {}
        self.blobs: dict[int, bytes] = {}
        self.n = 0
        self.fail_download = False

    def _id(self):
        self.n += 1
        return self.n

    def release(self, tag):
        return self.rels.get(tag)

    def ensure_release(self, tag, body):
        if tag not in self.rels:
            self.rels[tag] = {"id": self._id(), "tag_name": tag, "assets": []}
        return self.rels[tag]

    def assets(self, rel):
        return list(rel["assets"])

    def releases(self):
        return list(self.rels.values())

    def download(self, asset, dest):
        if self.fail_download:
            raise OSError("network down")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.blobs[asset["id"]])

    def upload(self, rel, name, fp, label):
        a = {"id": self._id(), "name": name, "label": label, "size": fp.stat().st_size, "url": "x", "updated_at": "t"}
        self.blobs[a["id"]] = fp.read_bytes()
        rel["assets"].append(a)
        return a

    def delete_asset(self, aid):
        for r in self.rels.values():
            r["assets"] = [a for a in r["assets"] if a["id"] != aid]

    def rename_asset(self, aid, name, label):
        for r in self.rels.values():
            for a in r["assets"]:
                if a["id"] == aid:
                    a.update(name=name, label=label)
                    return a

    def json(self, method, path, body=None):  # prune 용
        if method == "DELETE" and path.startswith("/releases/") and "assets" not in path:
            rid = int(path.rsplit("/", 1)[1])
            self.rels = {k: v for k, v in self.rels.items() if v["id"] != rid}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    monkeypatch.setattr(ds, "MANIFEST", tmp_path / "data" / "data_store_manifest.json")
    monkeypatch.setattr(ds, "STATUS", tmp_path / "data" / "data_store_status.json")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(ds, "table_meta", lambda fp: json.loads(fp.read_text()) if fp.suffix == ".parquet" else {})
    return tmp_path


def put(root: Path, rel: str, rows: int, asof: str | None = None, pad: int = 0):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"rows": rows, **({"asof": asof} if asof else {}), "pad": "x" * pad}
    p.write_text(json.dumps(meta))
    return p


def test_name_roundtrip_and_groups():
    assert ds.asset_path(ds.asset_name("data/fin/multi.parquet")) == "data/fin/multi.parquet"
    assert ds.matches("data/flows/kr_inv_2027.parquet", ds.patterns("flows"))
    assert not ds.matches("data/hist/kr_2025.parquet", ds.patterns("hist"))   # 연도 파일은 git 유지
    with pytest.raises(SystemExit):
        ds.patterns("nope")


def test_label_roundtrip():
    m = {"sha256": "ab" * 32, "size": 10, "rows": 5, "asof": "2026-10-20"}
    assert ds.from_label(ds.to_label(m)) == m


def test_push_then_pull_restores_exact_bytes(repo):
    gh = FakeGH()
    put(repo, "data/kr_prices.parquet", 100, "2026-10-20")
    res = ds.push("prices", gh=gh, git_rev="abc123")
    assert [r["status"] for r in res["files"]] == ["uploaded"]
    man = json.loads((repo / "data" / "data_store_manifest.json").read_text())
    assert man["files"]["data/kr_prices.parquet"]["git_rev"] == "abc123"
    orig = (repo / "data/kr_prices.parquet").read_bytes()
    (repo / "data/kr_prices.parquet").unlink()                     # checkout 직후(파일 없음)
    out = ds.pull("prices", gh=gh)
    assert out["files"][0]["status"] == "ok" and (repo / "data/kr_prices.parquet").read_bytes() == orig
    assert ds.pull("prices", gh=gh)["files"][0]["status"] == "same"


def test_push_overwrites_same_name_single_asset(repo):
    gh = FakeGH()
    put(repo, "data/signals.parquet", 100, "2026-10-19")
    ds.push("signals", gh=gh)
    put(repo, "data/signals.parquet", 101, "2026-10-20")
    ds.push("signals", gh=gh)
    names = [a["name"] for a in gh.rels["data-latest"]["assets"]]
    assert names == ["data__signals.parquet"]                     # 덮어쓰기(삭제+업로드), 임시 이름 안 남음
    assert ds.push("signals", gh=gh)["files"][0]["status"] == "unchanged"


def test_push_blocks_regress_shrink_and_force(repo):
    gh = FakeGH()
    put(repo, "data/kr_prices.parquet", 100, "2026-10-20")
    ds.push("prices", gh=gh)
    put(repo, "data/kr_prices.parquet", 100, "2026-10-17")
    assert ds.push("prices", gh=gh)["files"][0]["status"] == "blocked_regress"
    put(repo, "data/kr_prices.parquet", 10, "2026-10-21")
    assert ds.push("prices", gh=gh)["files"][0]["status"] == "blocked_shrink"
    assert ds.push("prices", gh=gh, force=True)["files"][0]["status"] == "uploaded"


def test_push_blocked_when_this_run_pulled_fallback(repo, monkeypatch):
    gh = FakeGH()
    put(repo, "data/fin/multi.parquet", 100)
    ds.push("fin", gh=gh)
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    gh.fail_download = True
    monkeypatch.setattr(ds.time, "sleep", lambda s: None)
    (repo / "data/fin/multi.parquet").unlink()
    st = ds.pull("fin", gh=gh)["files"][0]["status"]
    assert st == "missing"                                         # 스냅샷·git 폴백도 없음
    put(repo, "data/fin/multi.parquet", 120)                       # 빈 바탕에서 새로 만든 판
    assert ds.push("fin", gh=gh)["files"][0]["status"] == "blocked_pull_fallback"


def test_pull_falls_back_to_snapshot_then_git(repo, monkeypatch):
    gh = FakeGH()
    monkeypatch.setattr(ds.time, "sleep", lambda s: None)
    p = put(repo, "data/hist/us_daily.parquet", 50, "2026-10-17")
    ds.snapshot(keep=8, day="20261017", gh=gh)
    ds.push("hist", gh=gh)
    p.unlink()
    gh.rels["data-latest"]["assets"].clear()                       # latest 자산 유실
    out = ds.pull("hist", gh=gh)
    assert out["files"][0]["status"] == "fallback_snapshot" and p.exists()
    assert out["ok"] is False


def test_pull_git_fallback(repo, monkeypatch):
    gh = FakeGH()
    ds.save_manifest({"tag": "data-latest", "files": {"data/kr_prices.parquet": {"git_rev": "deadbeef"}}})
    monkeypatch.setattr(ds, "_git_fallback", lambda path, rev, dest: (dest.parent.mkdir(parents=True, exist_ok=True),
                                                                      dest.write_text("old"))[1] > 0 and rev == "deadbeef")
    out = ds.pull("prices", gh=gh)                                 # 릴리스 자체가 없음
    assert out["files"][0]["status"] == "fallback_git"
    assert (repo / "data/kr_prices.parquet").read_text() == "old"


def test_snapshot_prunes_to_keep(repo):
    gh = FakeGH()
    put(repo, "data/signals.parquet", 5, "2026-10-01")
    for d in ["20260801", "20260808", "20260815", "20260822"]:
        ds.snapshot(keep=8, day=d, gh=gh)
    res = ds.snapshot(keep=2, day="20260829", gh=gh)
    assert sorted(t for t in gh.rels if t.startswith("data-2")) == ["data-20260822", "data-20260829"]
    assert res["pruned"] == ["data-20260801", "data-20260808", "data-20260815"]


def test_pull_dest_dir_does_not_touch_tree(repo, tmp_path_factory):
    gh = FakeGH()
    put(repo, "data/signals.parquet", 5, "2026-10-01")
    ds.snapshot(day="20261002", gh=gh)
    out_dir = tmp_path_factory.mktemp("restore")
    ds.pull("signals", tag="data-20261002", dest_root=out_dir, gh=gh)
    assert (out_dir / "data/signals.parquet").exists()


def test_manifest_one_line_per_file(repo):
    ds.save_manifest({"tag": "data-latest", "files": {"a": {"sha256": "1"}, "b": {"sha256": "2"}}})
    lines = (repo / "data" / "data_store_manifest.json").read_text().splitlines()
    assert sum(1 for x in lines if x.strip().startswith('"a"') or x.strip().startswith('"b"')) == 2
    assert json.loads("\n".join(lines))["files"]["b"]["sha256"] == "2"


def test_committed_manifest_valid_and_files_ignored():
    """커밋된 manifest 의 모든 파일은 .gitignore 로 추적 밖이어야 한다 (다시 커밋되면 저장소가 또 분다)."""
    mp = ROOT / "data" / "data_store_manifest.json"
    if not mp.exists():
        pytest.skip("manifest 없음")
    files = json.loads(mp.read_text())["files"]
    assert files
    if shutil.which("git") is None:
        pytest.skip("git 없음")
    import subprocess
    for f in files:
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", f])
        assert r.returncode == 0, f"{f} 가 .gitignore 에 없음"
        assert all(ds.matches(f, ds.GROUPS[g]) for g in [next(g for g in ds.GROUPS if ds.matches(f, ds.GROUPS[g]))])


def test_writer_workflows_pull_before_push():
    """push 하는 워크플로는 반드시 같은 그룹을 먼저 pull 한다(빈 바탕에서 만든 판으로 덮어쓰기 방지)."""
    wf = ROOT / ".github" / "workflows"
    for f in wf.glob("*.yml"):
        t = f.read_text(encoding="utf-8")
        if "data_store.py push" in t:
            assert t.index("data_store.py pull") < t.index("data_store.py push"), f.name
