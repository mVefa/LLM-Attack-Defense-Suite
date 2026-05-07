import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from target_bot import chat, BlockedByDefenseError, OutputLeakError


def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Merhaba! Sen kimsin?"

    print(f"[USER]   {query}")

    try:
        reply, report = chat(query)

        if report:
            kw = report.get("layer1_flagged_keywords", [])
            verdict = report.get("layer3_verdict", "—")
            print(f"[DEFENSE] L1 keywords={kw or '[]'}  L3={verdict}")

        print(f"[BOT]    {reply}")

    except BlockedByDefenseError as exc:
        print(f"[BLOCKED:input]  {exc}", file=sys.stderr)
        sys.exit(2)
    except OutputLeakError as exc:
        print(f"[BLOCKED:output] {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"[ERROR]  {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
