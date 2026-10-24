"""剪映（CapCut）云端 ASR —— 实测中文专名最准、9 秒出稿。

⚠️ 重要风险声明（不要删）：
1. 本引擎走的是**字节跳动剪映 PC 端的私有接口**，不是公开 API，没有 SLA，
   字节随时可能改协议或封禁，失效是预期内的，不是 bug。
2. 请求签名依赖一个**第三方中转服务**（默认 asrtools-update.bkfeng.top），
   意味着你的音频元数据会经过它。可用 LYCOSUB_JY_SIGN_URL 换成自建签名器。
3. 因此本引擎默认**不启用**，必须显式选择；离线引擎（funasr/whisper）才是默认路径。
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Callable

import httpx

from .base import ASREngine, ASRResult, EngineUnavailable, register

API_HOST = "https://lv-pc-api-sinfonlinec.ulikecam.com"
UPLOAD_BIZ = "pc-recognition"
SPACE_NAME = "lv-mac-recognition"
DEFAULT_SIGN_URL = "https://asrtools-update.bkfeng.top/sign"

UA_CLIENT = "Cronet/TTNetVersion:d4572e53 2024-06-12 QuicVersion:4bf243e0 2023-04-17"
UA_UPLOAD = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36 Thea/1.0.1"
)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k = _sign(("AWS4" + secret).encode("utf-8"), datestamp)
    k = _sign(k, region)
    k = _sign(k, service)
    return _sign(k, "aws4_request")


def _aws_signature(secret: str, params: str, headers: dict, region="cn", service="vod") -> str:
    canonical_headers = "\n".join(f"{k}:{v}" for k, v in headers.items()) + "\n"
    signed_headers = ";".join(headers.keys())
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_request = f"GET\n/\n{params}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    amzdate = headers["x-amz-date"]
    datestamp = amzdate.split("T")[0]
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amzdate}\n{scope}\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )
    return hmac.new(
        _signing_key(secret, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class JianYingEngine(ASREngine):
    name = "jianying"
    label = "剪映云端 ASR（中文专名最准 / 需联网 / 私有接口）"
    kind = "cloud"
    needs = ("httpx",)
    notes = "⚠️ 私有接口 + 第三方签名中转，可能随时失效。默认关闭，需显式启用。"

    def available(self) -> tuple[bool, str]:
        if os.environ.get("LYCOSUB_ENABLE_JIANYING") != "1":
            return False, "未启用：设置 LYCOSUB_ENABLE_JIANYING=1 后可用（私有接口，风险自负）"
        return super().available()

    # ---- 内部工具 ----

    @staticmethod
    def _tdid() -> str:
        i = str(datetime.datetime.now().year)[3]
        fr = 390 + int(i)
        ed = "3278516897751" if int(i) % 2 != 0 else f"{uuid.getnode():013d}"
        return f"{fr}{ed}"

    def _sign(self, client: httpx.Client, url_path: str, tdid: str) -> tuple[str, str]:
        now = str(int(time.time()))
        sign_url = os.environ.get("LYCOSUB_JY_SIGN_URL", DEFAULT_SIGN_URL)
        resp = client.post(
            sign_url,
            json={"url": url_path, "current_time": now, "pf": "4", "appvr": "6.6.0", "tdid": tdid},
            headers={"User-Agent": "lyco-sub/0.1", "tdid": tdid, "t": now},
            timeout=30,
        )
        resp.raise_for_status()
        sign = (resp.json() or {}).get("sign")
        if not sign:
            raise EngineUnavailable(f"签名服务无返回: {sign_url}")
        return sign.lower(), now

    def _headers(self, tdid: str, device_time: str, sign: str) -> dict:
        return {
            "User-Agent": UA_CLIENT,
            "appvr": "6.6.0",
            "device-time": str(device_time),
            "pf": "4",
            "sign": sign,
            "sign-ver": "1",
            "tdid": tdid,
        }

    # ---- 主流程 ----

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   **opts) -> ASRResult:
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(reason)

        def _p(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        with open(audio_path, "rb") as f:
            blob = f.read()
        crc32_hex = f"{__import__('zlib').crc32(blob) & 0xFFFFFFFF:08x}"
        tdid = self._tdid()
        t0 = time.time()

        with httpx.Client(timeout=120, follow_redirects=True) as client:
            _p(10, "申请上传凭证…")
            sign, dt = self._sign(client, "/lv/v1/upload_sign", tdid)
            r = client.post(
                f"{API_HOST}/lv/v1/upload_sign",
                content=json.dumps({"biz": UPLOAD_BIZ}),
                headers=self._headers(tdid, dt, sign),
            )
            r.raise_for_status()
            cred = r.json()["data"]
            access_key = cred["access_key_id"]
            secret_key = cred["secret_access_key"]
            session_token = cred["session_token"]

            _p(20, "申请存储地址…")
            params = (
                f"Action=ApplyUploadInner&FileSize={len(blob)}&FileType=object"
                f"&IsInner=1&SpaceName={SPACE_NAME}&Version=2020-11-19&s=5y0udbjapi"
            )
            t = datetime.datetime.now(datetime.timezone.utc)
            amz_date = t.strftime("%Y%m%dT%H%M%SZ")
            datestamp = t.strftime("%Y%m%d")
            aws_headers = {"x-amz-date": amz_date, "x-amz-security-token": session_token}
            signature = _aws_signature(secret_key, params, aws_headers)
            auth_header = (
                f"AWS4-HMAC-SHA256 Credential={access_key}/{datestamp}/cn/vod/aws4_request, "
                f"SignedHeaders=x-amz-date;x-amz-security-token, Signature={signature}"
            )
            aws_headers["authorization"] = auth_header
            r = client.get(f"https://vod.bytedanceapi.com/?{params}", headers=aws_headers)
            r.raise_for_status()
            info = r.json()["Result"]["UploadAddress"]
            store = info["StoreInfos"][0]
            store_uri = store["StoreUri"]
            upload_auth = store["Auth"]
            upload_id = store["UploadID"]
            upload_host = info["UploadHosts"][0]

            upload_headers = {
                "User-Agent": UA_UPLOAD,
                "Authorization": upload_auth,
                "Content-CRC32": crc32_hex,
            }

            _p(35, "上传音频…")
            base = f"https://{upload_host}/{store_uri}"
            client.put(f"{base}?partNumber=1&uploadID={upload_id}",
                       content=blob, headers=upload_headers).raise_for_status()
            client.post(f"{base}?uploadID={upload_id}",
                        content=f"1:{crc32_hex}", headers=upload_headers)
            client.put(
                f"{base}?uploadID={upload_id}&partNumber=1&x-amz-security-token={session_token}",
                content=blob, headers=upload_headers,
            )

            _p(55, "提交识别任务…")
            sign, dt = self._sign(client, "/lv/v1/audio_subtitle/submit", tdid)
            r = client.post(
                f"{API_HOST}/lv/v1/audio_subtitle/submit",
                json={
                    "adjust_endtime": 200,
                    "audio": store_uri,
                    "caption_type": 2,
                    "client_request_id": "45faf98c-160f-4fae-a649-6d89b0fe35be",
                    "max_lines": 1,
                    "songs_info": [{"end_time": 6000, "id": "", "start_time": 0}],
                    "words_per_line": 16,
                },
                headers=self._headers(tdid, dt, sign),
            )
            r.raise_for_status()
            payload = r.json()
            if payload.get("ret") != "0":
                raise EngineUnavailable(f"剪映接口错误: {payload.get('errmsg')} (ret={payload.get('ret')})")
            query_id = payload["data"]["id"]

            _p(70, "等待识别结果…")
            for _ in range(120):
                sign, dt = self._sign(client, "/lv/v1/audio_subtitle/query", tdid)
                r = client.post(
                    f"{API_HOST}/lv/v1/audio_subtitle/query",
                    json={"id": query_id, "pack_options": {"need_attribute": True}},
                    headers=self._headers(tdid, dt, sign),
                )
                r.raise_for_status()
                data = r.json()
                if data.get("ret") != "0":
                    raise EngineUnavailable(f"剪映查询错误: {data.get('errmsg')}")
                utterances = (data.get("data") or {}).get("utterances")
                if utterances:
                    break
                time.sleep(1.0)
            else:
                raise EngineUnavailable("剪映识别超时（120s 未返回）")

        segments = [
            {"start": round(u["start_time"] / 1000.0, 3),
             "end": round(u["end_time"] / 1000.0, 3),
             "text": (u.get("text") or "").strip()}
            for u in utterances
            if (u.get("text") or "").strip()
        ]

        _p(95, f"得到 {len(segments)} 句")
        return ASRResult(
            engine=self.name,
            segments=segments,
            language=language or "zh",
            duration=segments[-1]["end"] if segments else 0.0,
            elapsed=time.time() - t0,
            meta={"private_api": True, "sign_relay": os.environ.get("LYCOSUB_JY_SIGN_URL", DEFAULT_SIGN_URL)},
        )


register(JianYingEngine())
