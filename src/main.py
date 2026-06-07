import argparse
import sys
from dotenv import load_dotenv


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Oxted & Hurst Green Bugle")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Generate and publish one edition now")
    sub.add_parser("start", help="Start the scheduled runner")

    args = parser.parse_args()

    if args.command == "run":
        from .scheduler.runner import Runner
        Runner().run_once()
    elif args.command == "start":
        from .scheduler.runner import Runner
        Runner().start()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
