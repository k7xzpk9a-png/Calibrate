"""Check the ROC de-rating auto-cal ordering (fig 9-53).

The calibrator assigns Drag index 1..25 by sorting the 25 curves on their y at
the right end (max x), descending. fig 9-53 was hand-tagged with the same 1..25
in its `zp` field, so that's our ground truth: the sort must reproduce it.

Run: python3 test_roc_derate.py
"""
import json, re

SERVED = "/home/yorian/AndroidStudioProjects/nh90-svelte/static/lookup.json"


def y_at_max_x(d: str) -> float:
    nums = list(map(float, re.findall(r"-?\d+\.?\d*", d)))
    pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    return max(pts, key=lambda p: p[0])[1]  # y of the point with the largest x


def main():
    curves = json.load(open(SERVED))["figs"]["9-53"]["tagged"]["curves"]
    assert len(curves) == 25, f"expected 25 drag curves, got {len(curves)}"
    ordered = sorted(curves, key=lambda c: y_at_max_x(c["d"]), reverse=True)
    got = [c.get("zp") for c in ordered]  # hand tag stored drag index in `zp`
    assert got == list(range(1, 26)), f"sort != 1..25 hand tags: {got}"
    print("ok: right-end-y sort reproduces drag 1..25")


if __name__ == "__main__":
    main()
