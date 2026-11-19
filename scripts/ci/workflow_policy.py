"""Choose coverage conservatively; no token/API permissions are needed."""
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen

SHA = re.compile(r"^[0-9a-f]{40}$")
DATA_FILES = {
    "pipeline/nab_business_confidence_raw.csv",
    "pipeline/.cache/model_output/vintages/vintage_tracking.csv",
    "nowcasting_v3/data/gdp_first_release.csv",
    "nowcasting_v3/data/first_print_misses.csv",
}


def data_or_docs(path):
    suffix = Path(path).suffix.lower()
    return (path in DATA_FILES or path == "README.md" or
            (path.startswith("docs/") and suffix == ".md") or
            (path.startswith("data/") and suffix in {".json", ".csv"}) or
            (path.startswith("nowcasting_v2/data_raw/") and
             suffix in {".csv", ".json", ".xls", ".xlsx"}))


def publish_context(event, ref):
    return event in {"push", "workflow_dispatch"} and ref == "refs/heads/main"


def choose(event, ref, verification="auto", base=None, paths=None):
    base = base if isinstance(base, str) and SHA.fullmatch(base) else None
    publish = publish_context(event, ref)
    if verification not in {"auto", "full"}:
        raise ValueError("Unknown verification mode")
    if event == "pull_request":
        full, reason = True, "pull-request"
    elif verification == "full":
        full, reason = True, "manual-full"
    elif not publish:
        full, reason = True, "non-production-verification"
    elif not base or paths is None:
        full, reason = True, "published-baseline-unavailable"
    elif all(data_or_docs(path) for path in paths):
        full, reason = False, "same-code-as-published-build"
    else:
        full, reason = True, "unpublished-code-or-unknown-path"
    return {"full_qa": str(full).lower(), "publish": str(publish).lower(),
            "reason": reason, "base_commit": base or "unavailable"}


def published_commit():
    req = Request("https://nowcast.wlsn.me/?ci-baseline=" + str(time.time_ns()),
                  headers={"Cache-Control": "no-cache", "User-Agent": "nowcast-ci-plan"})
    with urlopen(req, timeout=10) as response:
        text = response.read(16 * 1024 * 1024).decode("utf-8")
    match = re.search(r'<meta[^>]*name="build-commit"[^>]*content="([0-9a-f]{40})"', text)
    if not match:
        raise ValueError("Published build has no valid commit marker")
    return match[1]


def changed_paths(base, head):
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise ValueError("Invalid commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", base, head])
    return [p.decode("utf-8") for p in raw.split(b"\0") if p]


def plan():
    event, ref = os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"]
    verification = os.environ.get("VERIFICATION", "auto")
    base, paths = None, None
    if publish_context(event, ref) and verification == "auto":
        try:
            base = published_commit()
            paths = changed_paths(base, os.environ["GITHUB_SHA"])
        except Exception as exc:
            # A failed lookup must add coverage, never remove it.
            print(f"Baseline unavailable ({type(exc).__name__}); requiring full QA")
            base = None
    result = choose(event, ref, verification, base, paths)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in result.items():
            output.write(f"{key}={value}\n")
    print(json.dumps(result, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write("## Candidate coverage\n\n" +
                          f"Full Chromium + WebKit required: **{result['full_qa']}**\n\n" +
                          f"Reason: `{result['reason']}`; published baseline: `{result['base_commit']}`.\n\n" +
                          "This run builds and smoke-tests its own SHA; no PR/cross-run export is reused.\n")
    return result


def gate(needs, event, ref):
    candidate = needs.get("candidate", {})
    if candidate.get("result") != "success":
        raise ValueError("Candidate build/guards/smoke did not succeed")
    outputs = candidate.get("outputs", {})
    full = outputs.get("full_qa")
    if full not in {"true", "false"}:
        raise ValueError("Coverage plan missing or invalid")
    expected_publish = str(publish_context(event, ref)).lower()
    if outputs.get("publish") != expected_publish:
        raise ValueError("Publication context does not match the plan")
    if not re.fullmatch(r"[0-9]+", outputs.get("artifact_id", "")):
        raise ValueError("Immutable candidate artifact ID is missing")
    for job in ("chromium", "webkit"):
        result = needs.get(job, {}).get("result")
        allowed = {"success"} if full == "true" else {"success", "skipped"}
        if result not in allowed:
            raise ValueError(f"Required {job} coverage was {result!r}")
    return {"full_qa": full, "publish": expected_publish, "result": "passed"}


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["plan"]:
        plan()
    elif sys.argv[1:] == ["gate"]:
        print(json.dumps(gate(json.loads(os.environ["NEEDS_JSON"]),
                              os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])))
    else:
        raise SystemExit("Use plan or gate")
