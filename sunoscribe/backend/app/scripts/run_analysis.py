from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.services.audio_analysis_service import AudioAnalysisOptions, AudioAnalysisService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run end-to-end audio analysis pipeline")
    parser.add_argument("--input", required=True, help="Input audio file path")
    parser.add_argument("--project-id", required=True, help="Project workspace ID")
    parser.add_argument(
        "--enable-llm-refine",
        action="store_true",
        help="Enable alignment LLM refine stage",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    service = AudioAnalysisService()
    options = AudioAnalysisOptions(
        project_id=args.project_id,
        enable_llm_refine=bool(args.enable_llm_refine),
    )

    result = await service.process_audio(args.input, options)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
