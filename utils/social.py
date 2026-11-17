"""Uploading finished clips to social media. Async (aiohttp), one function per platform, each returning
(external_id, url) or raising PostError.

- Facebook Reels: video_reels start -> upload the file to rupload.facebook.com -> finish with video_state=PUBLISHED.
- Instagram Reels: a REELS container with upload_type=resumable -> upload the file -> wait until FINISHED -> publish.
- YouTube Shorts: resumable upload with an OAuth token file (refreshed and saved back).
- TikTok: upload to the creator's drafts ("inbox"), or a direct post (needs TikTok's audit to be public).
Nothing here touches Discord or the database.
"""
import asyncio
import json
import os
import time

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=600)


class PostError(Exception):
    pass


async def _read(path):
    return await asyncio.get_running_loop().run_in_executor(None, lambda: open(path, "rb").read())


async def _json(resp, what):
    try:
        body = await resp.json(content_type=None)
    except (aiohttp.ContentTypeError, ValueError):
        body = {"raw": (await resp.text())[:300]}
    if resp.status >= 400 or (isinstance(body, dict) and body.get("error") and not body.get("data")):
        err = body.get("error") if isinstance(body, dict) else body
        if isinstance(err, dict):
            err = err.get("message") or err.get("error_user_msg") or err
        raise PostError(f"{what}: HTTP {resp.status}: {err}")
    return body


# --------------------------------------------------------------------------- #
# Meta (Facebook Page + Instagram professional account)
# --------------------------------------------------------------------------- #
class Meta:
    def __init__(self, token, page_id, ig_id, version="v23.0"):
        self.token, self.page_id, self.ig_id, self.v = token, page_id, ig_id, version
        self.graph = f"https://graph.facebook.com/{version}"
        self._page_token = None

    async def page_token(self, s):
        if not self._page_token:
            async with s.get(f"{self.graph}/{self.page_id}",
                             params={"fields": "access_token", "access_token": self.token}) as r:
                self._page_token = (await _json(r, "page token"))["access_token"]
        return self._page_token

    async def _rupload(self, s, url, token, data):
        headers = {"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))}
        async with s.post(url, headers=headers, data=data) as r:
            await _json(r, "upload")

    async def facebook_reel(self, path, description):
        data = await _read(path)
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            token = await self.page_token(s)
            async with s.post(f"{self.graph}/{self.page_id}/video_reels",
                              data={"upload_phase": "start", "access_token": token}) as r:
                start = await _json(r, "facebook start")
            video_id = start["video_id"]
            await self._rupload(s, start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{self.v}/{video_id}",
                                token, data)
            async with s.post(f"{self.graph}/{self.page_id}/video_reels",
                              data={"upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
                                    "description": description, "access_token": token}) as r:
                await _json(r, "facebook finish")
        return video_id, f"https://www.facebook.com/reel/{video_id}"

    async def instagram_reel(self, path, caption, wait=300):
        data = await _read(path)
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.post(f"{self.graph}/{self.ig_id}/media",
                              data={"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                                    "share_to_feed": "true", "access_token": self.token}) as r:
                container = await _json(r, "instagram container")
            cid = container["id"]
            await self._rupload(s, container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.v}/{cid}",
                                self.token, data)
            status, deadline = None, time.monotonic() + wait
            while time.monotonic() < deadline:
                async with s.get(f"{self.graph}/{cid}", params={"fields": "status_code,status",
                                                                  "access_token": self.token}) as r:
                    info = await _json(r, "instagram status")
                status = info.get("status_code")
                if status == "FINISHED":
                    break
                if status in ("ERROR", "EXPIRED"):
                    raise PostError(f"instagram processing: {info.get('status') or status}")
                await asyncio.sleep(10)
            if status != "FINISHED":
                raise PostError(f"instagram processing took longer than {wait} s (status {status})")
            async with s.post(f"{self.graph}/{self.ig_id}/media_publish",
                              data={"creation_id": cid, "access_token": self.token}) as r:
                media_id = (await _json(r, "instagram publish"))["id"]
            async with s.get(f"{self.graph}/{media_id}", params={"fields": "permalink", "access_token": self.token}) as r:
                link = (await _json(r, "instagram permalink")).get("permalink", "")
        return media_id, link


# --------------------------------------------------------------------------- #
# YouTube
# --------------------------------------------------------------------------- #
class YouTube:
    """``token_file`` is the authorized-user JSON from Google's InstalledAppFlow (token, refresh_token, client_id,
    client_secret, token_uri, expiry)."""

    def __init__(self, token_file, privacy="private"):
        self.token_file, self.privacy = token_file, privacy

    async def _access_token(self, s):
        tok = json.load(open(self.token_file, encoding="utf8"))
        async with s.post(tok.get("token_uri", "https://oauth2.googleapis.com/token"),
                          data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                "client_id": tok["client_id"], "client_secret": tok["client_secret"]}) as r:
            fresh = await _json(r, "youtube token")
        tok["token"] = fresh["access_token"]
        json.dump(tok, open(self.token_file, "w", encoding="utf8"))
        return tok["token"]

    async def short(self, path, title, description):
        data = await _read(path)
        body = {"snippet": {"title": title, "description": description, "categoryId": "20"},
                "status": {"privacyStatus": self.privacy, "selfDeclaredMadeForKids": False}}
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            token = await self._access_token(s)
            async with s.post("https://www.googleapis.com/upload/youtube/v3/videos",
                              params={"uploadType": "resumable", "part": "snippet,status"},
                              headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                       "X-Upload-Content-Length": str(len(data))}, json=body) as r:
                if r.status >= 400:
                    await _json(r, "youtube start")
                location = r.headers.get("Location")
            if not location:
                raise PostError("youtube start: no upload address")
            async with s.put(location, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"},
                             data=data) as r:
                video = await _json(r, "youtube upload")
        return video["id"], f"https://youtube.com/shorts/{video['id']}"


# --------------------------------------------------------------------------- #
# TikTok
# --------------------------------------------------------------------------- #
class TikTok:
    """``client_file``: client_key=/client_secret= lines. ``token_file``: the JSON from the OAuth exchange
    (access_token, refresh_token, ...); refreshed and saved back (TikTok rotates refresh tokens)."""
    API = "https://open.tiktokapis.com/v2"

    def __init__(self, client_file, token_file, mode="inbox"):
        self.client_file, self.token_file, self.mode = client_file, token_file, mode

    async def _access_token(self, s):
        client = dict(line.strip().split("=", 1) for line in open(self.client_file, encoding="utf8") if "=" in line)
        tok = json.load(open(self.token_file, encoding="utf8"))
        async with s.post(f"{self.API}/oauth/token/",
                          data={"client_key": client["client_key"], "client_secret": client["client_secret"],
                                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}) as r:
            fresh = await _json(r, "tiktok token")
        tok.update(fresh)
        json.dump(tok, open(self.token_file, "w", encoding="utf8"))
        return tok["access_token"]

    async def video(self, path, title):
        data = await _read(path)
        size = len(data)
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            token = await self._access_token(s)
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
            if self.mode == "direct":
                url = f"{self.API}/post/publish/video/init/"
                payload = {"post_info": {"title": title[:2200], "privacy_level": "SELF_ONLY"}, "source_info": source}
            else:
                url = f"{self.API}/post/publish/inbox/video/init/"
                payload = {"source_info": source}
            async with s.post(url, headers=headers, json=payload) as r:
                init = (await _json(r, "tiktok init"))["data"]
            async with s.put(init["upload_url"], data=data,
                             headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"}) as r:
                if r.status >= 400:
                    raise PostError(f"tiktok upload: HTTP {r.status}")
        return init["publish_id"], ""
