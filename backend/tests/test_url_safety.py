"""Tests de validación SSRF para URLs externas."""

from utils.url_safety import is_safe_external_url


def test_blocks_localhost():
    assert is_safe_external_url("http://localhost/admin") is False
    assert is_safe_external_url("http://127.0.0.1/") is False


def test_blocks_private_ip_literal():
    assert is_safe_external_url("http://192.168.1.1/admin") is False
    assert is_safe_external_url("http://10.0.0.1/metadata") is False
    assert is_safe_external_url("http://169.254.169.254/latest/meta-data/") is False


def test_allows_public_https():
    assert is_safe_external_url("https://example.com/docs") is True


import pytest

from utils.url_safety import is_safe_external_url_async


@pytest.mark.asyncio
async def test_async_blocks_localhost():
    assert await is_safe_external_url_async("http://localhost/admin") is False


@pytest.mark.asyncio
async def test_async_blocks_private_range():
    assert await is_safe_external_url_async("http://192.168.1.1/admin") is False
    assert await is_safe_external_url_async("http://10.0.0.1/metadata") is False
    assert await is_safe_external_url_async("http://169.254.169.254/latest/meta-data/") is False


@pytest.mark.asyncio
async def test_async_allows_public_url():
    assert await is_safe_external_url_async("https://example.com/docs") is True


@pytest.mark.asyncio
async def test_async_blocks_invalid_scheme():
    assert await is_safe_external_url_async("ftp://example.com") is False
