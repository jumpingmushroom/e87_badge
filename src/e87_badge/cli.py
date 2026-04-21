"""`e87` command-line tool — thin wrapper over `E87Client`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys
from typing import Sequence

from .client import E87Client
from .discovery import discover, find_one

log = logging.getLogger("e87")


# ── Argument parser ────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e87",
        description="Open client for the E-Badge E87 / L8 LED BLE badge.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging (per-frame wire dumps).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # discover
    sub.add_parser("discover", help="Scan for nearby E87 badges.")

    # info
    p_info = sub.add_parser("info", help="Print device info (connects briefly).")
    p_info.add_argument("--address", required=True, help="BLE MAC address of the badge.")

    # image
    p_img = sub.add_parser("image", help="Upload a static image file.")
    p_img.add_argument("path", type=pathlib.Path)
    p_img.add_argument("--address", help="Badge MAC; if omitted, auto-discovered.")

    # text
    p_txt = sub.add_parser("text", help="Render text and upload as a static image.")
    p_txt.add_argument("text", help="Text to render.")
    p_txt.add_argument("--address", help="Badge MAC; if omitted, auto-discovered.")
    p_txt.add_argument("--font", help="Path to a .ttf font.")
    p_txt.add_argument("--size", type=int, default=72)
    p_txt.add_argument("--colour", default="white", help="Text colour.")
    p_txt.add_argument("--bg", default="black", help="Background colour.")

    # slideshow
    p_ss = sub.add_parser(
        "slideshow",
        help="Upload multiple images as an animated slideshow (MJPG AVI).",
    )
    p_ss.add_argument("paths", type=pathlib.Path, nargs="+")
    p_ss.add_argument("--address", help="Badge MAC; if omitted, auto-discovered.")
    p_ss.add_argument(
        "--ms", type=int, default=500,
        help="Duration each frame is displayed, in milliseconds.",
    )

    # gif
    p_gif = sub.add_parser("gif", help="Upload an animated GIF file.")
    p_gif.add_argument("path", type=pathlib.Path)
    p_gif.add_argument("--address", help="Badge MAC; if omitted, auto-discovered.")
    p_gif.add_argument(
        "--max-fps", type=int, default=24,
        help="Clamp output fps to this upper bound.",
    )

    # danmaku
    p_dm = sub.add_parser(
        "danmaku", help="Render scrolling-text danmaku and upload as AVI.",
    )
    p_dm.add_argument("text", help="Scrolling text string.")
    p_dm.add_argument("--address", help="Badge MAC; if omitted, auto-discovered.")
    p_dm.add_argument("--font", help="Path to a .ttf font.")
    p_dm.add_argument("--font-size", type=int, default=64)
    p_dm.add_argument("--fg", default="white", help="Text colour.")
    p_dm.add_argument("--bg", default="black", help="Background colour.")
    p_dm.add_argument(
        "--speed", type=int, default=4, dest="speed_px_per_frame",
        help="Scroll speed in pixels per frame.",
    )
    p_dm.add_argument("--fps", type=int, default=20)

    return parser


# ── Command implementations ────────────────────────────────────────────────

async def _cmd_discover(_args: argparse.Namespace) -> int:
    devices = await discover(timeout=10.0)
    if not devices:
        print("No E87 badges found.", file=sys.stderr)
        return 1
    for dev in devices:
        print(f"{dev.address}\t{dev.name or ''}")
    return 0


async def _resolve_address(address: str | None) -> str:
    if address is not None:
        return address
    dev = await find_one(timeout=12.0)
    if dev is None:
        raise SystemExit("No badge found via auto-discovery. Pass --address.")
    return dev.address


async def _cmd_info(args: argparse.Namespace) -> int:
    async with E87Client(args.address) as _client:
        # v1 doesn't expose device info yet; successful connect+auth is
        # enough to demonstrate reachability. Future: parse the FD01
        # 0x9E..C7 frame captured during auth for firmware/model info.
        print(f"Connected to {args.address} and authenticated.")
    return 0


async def _cmd_image(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address)
    async with E87Client(address) as client:
        await client.send_image(args.path)
    return 0


async def _cmd_text(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address)
    async with E87Client(address) as client:
        await client.send_text(
            args.text,
            font=args.font,
            size=args.size,
            colour=args.colour,
            bg=args.bg,
        )
    return 0


async def _cmd_slideshow(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address)
    async with E87Client(address) as client:
        await client.send_slideshow(args.paths, frame_ms=args.ms)
    return 0


async def _cmd_gif(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address)
    async with E87Client(address) as client:
        await client.send_gif(args.path, max_fps=args.max_fps)
    return 0


async def _cmd_danmaku(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address)
    async with E87Client(address) as client:
        await client.send_danmaku(
            args.text,
            fg=args.fg,
            bg=args.bg,
            font=args.font,
            font_size=args.font_size,
            speed_px_per_frame=args.speed_px_per_frame,
            fps=args.fps,
        )
    return 0


_DISPATCH = {
    "discover": _cmd_discover,
    "info": _cmd_info,
    "image": _cmd_image,
    "text": _cmd_text,
    "slideshow": _cmd_slideshow,
    "gif": _cmd_gif,
    "danmaku": _cmd_danmaku,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    handler = _DISPATCH[args.cmd]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        return 130
    except Exception as exc:  # pragma: no cover - CLI surface
        log.error("%s failed: %s", args.cmd, exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
