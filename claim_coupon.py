#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美团优惠券每日自动领取 - 云端版
通过 GitHub Actions 定时触发，无需本地电脑开机。
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import httpx

# 北京时间 UTC+8
UTC8 = timezone(timedelta(hours=8))
BASE_URL = "https://peppermall.meituan.com"
ISSUE_PATH = "/eds/standard/equity/pkg/issue/claw"


def main():
    # 从环境变量读取凭证（GitHub Secrets 注入）
    user_token = os.environ.get("MT_USER_TOKEN", "")
    phone_masked = os.environ.get("MT_PHONE_MASKED", "")
    sub_channel_code = os.environ.get("MT_SUB_CHANNEL_CODE", "")

    if not user_token or not phone_masked or not sub_channel_code:
        print(json.dumps({
            "success": False,
            "error": "MISSING_CREDENTIALS",
            "message": "缺少凭证环境变量，请检查 GitHub Secrets 配置"
        }, ensure_ascii=False))
        sys.exit(1)

    # 生成当天领券唯一键
    today = datetime.now(UTC8).strftime("%Y%m%d")
    redeem_code = hashlib.md5(
        f"{user_token}_{phone_masked}_{today}".encode("utf-8")
    ).hexdigest()

    # 构造请求
    body = {
        "subChannelCode": sub_channel_code,
        "token": user_token,
        "equityPkgRedeemCode": redeem_code
    }

    print(f"[{datetime.now(UTC8).strftime('%Y-%m-%d %H:%M:%S')}] 开始领取美团优惠券...")

    try:
        resp = httpx.post(
            BASE_URL + ISSUE_PATH,
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=15,
            verify=True
        )
        print(f"HTTP 状态码：{resp.status_code}")
        try:
            resp_data = resp.json()
        except json.JSONDecodeError:
            print(json.dumps({
                "success": False,
                "error": "INVALID_RESPONSE",
                "message": "美团接口返回了非 JSON 响应",
                "status_code": resp.status_code,
                "response_preview": resp.text[:500],
            }, ensure_ascii=False))
            sys.exit(1)
    except httpx.TimeoutException:
        print(json.dumps({
            "success": False,
            "error": "TIMEOUT",
            "message": "请求超时，请稍后重试"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": "NETWORK_ERROR",
            "message": f"网络异常：{str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)

    code = resp_data.get("code")
    message = resp_data.get("message", "")
    data = resp_data.get("data")
    if data is None:
        data = {}

    print("接口返回：")
    print(json.dumps({
        "code": code,
        "message": message,
        "data_type": type(data).__name__,
        "data_keys": list(data.keys()) if isinstance(data, dict) else [],
    }, ensure_ascii=False))

    # 错误码映射
    ERROR_MAP = {
        4009: ("ACTIVITY_ENDED", "活动已结束，暂时无法领取"),
        4010: ("ALREADY_RECEIVED", "今天已领取过美团权益"),
        4011: ("QUOTA_EXHAUSTED", "本次活动权益已发放完毕"),
    }

    if code == 0:
        # 发券成功
        if not isinstance(data, dict):
            print(json.dumps({
                "success": False,
                "error": "INVALID_DATA",
                "message": "美团接口 data 字段格式异常",
                "data_type": type(data).__name__,
            }, ensure_ascii=False))
            sys.exit(1)

        success_list = data.get("successEquityList", [])
        print(f"\n{'='*50}")
        if success_list:
            print(f"🎉 美团权益领取成功！共 {len(success_list)} 张优惠券：\n")
        else:
            print("接口返回成功，但没有返回优惠券明细。\n")

        for i, equity in enumerate(success_list, 1):
            name = equity.get("userEquityName", "-")
            discount = equity.get("discountAmountYuanStr", "-")
            price_limit_type = equity.get("priceLimitType", 1)
            price_limit = equity.get("priceLimitAmountYuanStr", "")

            if price_limit_type == 1:
                condition = "无门槛"
            else:
                condition = f"满{price_limit}元可用"

            begin_ts = equity.get("beginTime", 0)
            end_ts = equity.get("endTime", 0)
            valid_start = datetime.fromtimestamp(begin_ts / 1000, tz=UTC8).strftime("%Y-%m-%d") if begin_ts else "-"
            valid_end = datetime.fromtimestamp(end_ts / 1000, tz=UTC8).strftime("%Y-%m-%d") if end_ts else "-"

            print(f"  [{i}] {name}")
            print(f"      面额：{discount} 元（{condition}）")
            print(f"      有效期：{valid_start} 至 {valid_end}")
            print()

        print(f"{'='*50}")
        if success_list:
            print(f"温馨提示：券已存入美团账户，可在美团 App「我的-红包卡券」查看使用。")

        # 输出结构化结果供 workflow 使用
        result = {
            "success": True,
            "coupon_count": len(success_list),
            "coupons": [
                {
                    "name": e.get("userEquityName", "-"),
                    "discount": e.get("discountAmountYuanStr", "-"),
                }
                for e in success_list
            ]
        }
        # 写入 GitHub Actions output
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"result={json.dumps(result, ensure_ascii=False)}\n")

    elif code in ERROR_MAP:
        err_key, err_msg = ERROR_MAP[code]
        print(f"\n⚠️ {err_msg}")
        if code == 4010:
            print("（每天只能领取一次，明天再来哦~）")
        sys.exit(0)  # 已领取不算失败
    else:
        print(f"\n❌ 领取失败（错误码：{code}，{message}）")
        print("完整响应：")
        print(json.dumps(resp_data, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
