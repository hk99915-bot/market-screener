#!/usr/bin/env python3
"""한국어 문장 교정 검사 — 외부 전송 없음(10/28 겸이 "규칙만 옮겨").

출처: SolarLLM/human-proofreader-mcp(MIT) README 의 규칙·측정 항목을 저장소 안 규칙 검사로 옮김.
모델 호출·네트워크 없음 — 판정은 코드가 하므로 같은 입력이면 같은 결과.

  python3 scripts/proofcheck.py read FILE        # 진단: 문장 길이·번역투·피동·상투어
  python3 scripts/proofcheck.py compare ORIG NEW # 교정본 대조: 새 숫자·새 문장·변경률·말투·인용 보존
종료코드: compare 에서 차단(block)이 있으면 2.
"""
import argparse, difflib, json, re, sys

LONG = 60          # 한 문장 글자 수가 이 이상이면 '긴 문장'
TRANSLATIONESE = [r"에\s*있어서", r"을\s*통해(?:서)?", r"를\s*통해(?:서)?", r"에\s*대한", r"에\s*대해(?:서)?",
                  r"으로\s*인해", r"로\s*인해", r"하는\s*것이\s*(?:필요|중요)하다", r"할\s*수\s*있을\s*것이다",
                  r"것으로\s*보여진다", r"에\s*의해", r"을\s*가지고\s*있다", r"를\s*가지고\s*있다"]
PASSIVE = [r"되어지", r"되어진", r"보여지", r"보여진", r"만들어지", r"쓰여지", r"읽혀지", r"되었다고\s*보여"]
CLICHE = [r"주목할\s*만하다", r"귀추가\s*주목", r"시사하는\s*바가\s*크다", r"의미가\s*크다", r"한\s*단계\s*도약",
          r"새로운\s*지평", r"패러다임", r"게임\s*체인저", r"무궁무진", r"기대를\s*모으", r"눈길을\s*끈다"]
NUM = re.compile(r"[−\-+]?\d[\d,]*(?:\.\d+)?\s*(?:%p|%|bp|배|조|억|만|원|주|일|개월|년)?")
QUOTE = re.compile(r"[\"“]([^\"”]{2,})[\"”]|'([^']{2,})'|‘([^’]{2,})’")
POLITE = re.compile(r"(?:습니다|입니다|해요|이에요|예요|세요|어요|아요)[.!?]?\s*$")
PLAIN = re.compile(r"(?:다|함|음|임|됨)[.!?]?\s*$")


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip() and not p.strip().startswith(("#", "|", "```"))]


def hits(pats, text):
    return sum(len(re.findall(p, text)) for p in pats)


def read(text: str) -> dict:
    S = sentences(text)
    lens = [len(s) for s in S] or [0]
    long_s = [s[:40] for s in S if len(s) >= LONG]
    r = {"sentences": len(S), "avg_len": round(sum(lens) / len(lens), 1), "long": len(long_s), "long_examples": long_s[:3],
         "translationese": hits(TRANSLATIONESE, text), "passive": hits(PASSIVE, text), "cliche": hits(CLICHE, text)}
    # 점수(0~100): 긴 문장·번역투·피동·상투어 비율로 감점 — 참고값(검증 전), 판정 기준 아님
    n = max(len(S), 1)
    pen = 40 * r["long"] / n + 25 * min(1, r["translationese"] / n) + 20 * min(1, r["passive"] / n) + 15 * min(1, r["cliche"] / n)
    r["score"] = round(max(0, 100 - pen))
    return r


def register(text: str) -> str:
    S = sentences(text)
    p = sum(1 for s in S if POLITE.search(s)); q = sum(1 for s in S if PLAIN.search(s))
    return "polite" if p > q else "plain" if q > p else "mixed"


def compare(orig: str, new: str, keep: list[str] | None = None) -> dict:
    block, warn = [], []
    on, nn = set(NUM.findall(orig)), NUM.findall(new)
    added_nums = sorted({x.strip() for x in nn if x.strip() and x not in on and any(c.isdigit() for c in x)})
    if added_nums:
        block.append(f"원문에 없는 숫자: {', '.join(added_nums[:5])}")
    os_ = sentences(orig)
    new_sents = [s for s in sentences(new) if max((difflib.SequenceMatcher(None, s, o).ratio() for o in os_), default=0) < 0.5]
    if new_sents:
        block.append(f"원문에 대응 없는 새 문장 {len(new_sents)}개: {new_sents[0][:40]}")
    ratio = 1 - difflib.SequenceMatcher(None, orig, new).ratio()
    if ratio >= 0.5:
        block.append(f"변경률 {ratio:.0%} ≥ 50% — 교정이 아니라 재작성")
    elif ratio >= 0.3:
        warn.append(f"변경률 {ratio:.0%} (30~50%)")
    if len(new) > len(orig) * 1.05:
        warn.append(f"길이 증가 {len(new) / max(len(orig), 1) - 1:+.0%} — 덧붙이기보다 줄이기")
    ro, rn = register(orig), register(new)
    if ro != "mixed" and rn != ro:
        block.append(f"말투 바뀜 {ro} → {rn}")
    for m in QUOTE.finditer(orig):
        q = next(g for g in m.groups() if g)
        if q not in new:
            block.append(f"인용 훼손: {q[:30]}")
    for k in keep or []:
        if k in orig and k not in new:
            block.append(f"고정 문장 바뀜: {k[:30]}")
    added_cliche = hits(CLICHE, new) - hits(CLICHE, orig)
    if added_cliche > 0:
        warn.append(f"상투어 {added_cliche}개 추가")
    if abs(len(sentences(new)) - len(os_)) >= max(2, len(os_) // 3):
        warn.append(f"문장 수 {len(os_)} → {len(sentences(new))} — 합치기·쪼개기 과다")
    return {"verdict": "block" if block else "warn" if warn else "ok", "block": block, "warn": warn, "change_ratio": round(ratio, 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("read"); a.add_argument("file")
    b = sp.add_parser("compare"); b.add_argument("orig"); b.add_argument("new"); b.add_argument("--keep", action="append", default=[])
    x = ap.parse_args(argv)
    if x.cmd == "read":
        print(json.dumps(read(open(x.file, encoding="utf-8").read()), ensure_ascii=False, indent=1))
        return 0
    r = compare(open(x.orig, encoding="utf-8").read(), open(x.new, encoding="utf-8").read(), x.keep)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 2 if r["verdict"] == "block" else 0


if __name__ == "__main__":
    sys.exit(main())
