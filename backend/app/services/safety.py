"""Validation helpers for public SaaS-facing media workflows."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

from app.config import get_settings

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SAFE_ASSET_RE = re.compile(r"^[A-Za-z0-9_. -]{1,180}$")


def safe_id(value: str, label: str = "id") -> str:
    raw = (value or "").strip()
    if not SAFE_ID_RE.fullmatch(raw):
        raise ValueError(f"Invalid {label}")
    return raw


def safe_asset_filename(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not SAFE_ASSET_RE.fullmatch(raw) or raw in {".", ".."}:
        raise ValueError("Asset filename is invalid")
    if os.path.isabs(raw) or "/" in raw or "\\" in raw or ".." in raw.split("."):
        raise ValueError("Asset filename must be a file inside the asset library")
    return raw


def _host_allowed(host: str) -> bool:
    allowed = get_settings().allowed_video_hosts
    if not allowed:
        return True
    host = host.lower().rstrip(".")
    return any(host == item or host.endswith(f".{item}") for item in allowed)


def _reject_private_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        raise ValueError("Private network video URLs are not allowed")


def _verify_public_dns(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Video URL host could not be verified") from exc
    for info in infos:
        _reject_private_ip(info[4][0])


def validate_public_video_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Enter a valid http or https video URL")
    if not parsed.hostname:
        raise ValueError("Video URL is missing a host")
    host = parsed.hostname.lower()
    try:
        _reject_private_ip(host)
    except ValueError as exc:
        if "Private network" in str(exc):
            raise
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local network video URLs are not allowed")
    if not _host_allowed(host):
        raise ValueError(f"Video URL host is not allowed: {host}")
    _verify_public_dns(host)
    return raw
