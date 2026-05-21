# -*- coding: utf-8 -*-
import os
import datetime
import time
from typing import Optional
from ZXDoc import ZXDoc, ZDoCANCfg, ZUdsRequest, ZUdsPort, ZCANFrameType, ZCANTpVersion, ZErrorCode, ZUdsResponse

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ==================== 配置参数 ====================
CHANNEL_INDEX = 1          # 激活的 CAN 通道索引
TESTER_ADDR = 0x7BA        # 诊断仪地址（响应 ID）
ECU_ADDR = 0x73A           # ECU 地址（请求 ID）

# UDS 服务 ID
SID_19 = 0x19
SID_14 = 0x14

SUB_DTCCLEAN_SESSION = 0xFF

P2_TIMEOUT_MS = 3000
P2X_TIMEOUT_MS = 4000

# ==================== 日志类 ====================
class TestLogger:
    def __init__(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(os.getcwd(), f"UDS_TestLog-诊断清除测试-01-001_{timestamp}.txt")
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(f"===== UDS 诊断测试开始 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        print(f"日志文件将保存至: {self.log_path}")

    def log(self, msg, is_error=False):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        if is_error:
            print(f"\033[91m{line}\033[0m")
        else:
            print(line)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

logger = TestLogger()

# ==================== UDS 请求封装 ====================
def uds_request(uds_if, req_addr, rsp_addr, request_bytes,
                expected_positive_sid: Optional[int] = None,
                allow_nrc: bool = False) -> Optional[ZUdsResponse]:
    """发送 UDS 请求并返回响应对象，失败或否定响应（若不允许）时返回 None"""
    req = ZUdsRequest(
        reqAddr=req_addr,
        rspAddr=rsp_addr,
        extend=False,
        suppressResponse=False,
        sid=request_bytes[0],
        data=bytes(request_bytes[1:])
    )
    resp = uds_if.request(req)
    if resp is None:
        logger.log("UDS 请求超时或无响应", is_error=True)
        return None
    if resp.status != 0:
        logger.log(f"UDS 请求失败: status={resp.status}, errorCode={resp.errorCode}", is_error=True)
        return None
    if resp.responseType == 1:  # Positive
        if expected_positive_sid is not None and resp.sid != expected_positive_sid:
            logger.log(f"正响应服务 ID 不匹配: 期望 0x{expected_positive_sid:02X}, 实际 0x{resp.sid:02X}", is_error=True)
            return None
        data_str = resp.data.hex().upper() if resp.data else ""
        logger.log(f"正响应: SID=0x{resp.sid:02X} Data={data_str}")
        return resp
    elif resp.responseType == 0:  # Negative
        logger.log(f"否定响应: NRC=0x{resp.NRC:02X}", is_error=not allow_nrc)
        return resp if allow_nrc else None
    else:
        logger.log(f"未知响应类型: {resp.responseType}", is_error=True)
        return None

# ==================== 主流程 ====================
def main():
    zxdoc = None
    uds_if = None
    test_passed = False  # 默认失败，成功后置为 True

    try:
        logger.log("=== 初始化 ZXDoc 连接 ===")
        zxdoc = ZXDoc()
        ret = zxdoc.connect(projectFilePath="", noTrayIcon=False)
        if ret != ZErrorCode.OK:
            logger.log(f"连接失败: {ret}", is_error=True)
            return
        logger.log("ZXDoc 连接成功")

        zxdoc.start_measurement()
        time.sleep(0.5)

        # 创建 DoCAN 接口
        cfg = ZDoCANCfg(
            udsPort=ZUdsPort.Hardware,          # 硬件协议栈
            channelIndex=CHANNEL_INDEX,
            frameType=ZCANFrameType.CAN,
            protocolVersion=ZCANTpVersion.ISO15765_2_2004,
            fillByte=0xAA,
            isfillByte=True,
            p2Timeout=P2_TIMEOUT_MS,
            p2xTimeout=P2X_TIMEOUT_MS,
            isModifyEcuSTmin=False,
            remoteSTmin=0,
            localSTmin=0,
            blockSize=0,
            fcTimeout=0
        )
        uds_if = zxdoc.create_uds_interface(cfg)
        if uds_if is None:
            logger.log("创建 DoCAN 诊断接口失败", is_error=True)
            return
        logger.log("DoCAN 接口创建成功")

        # ---------- 读取初始 DTC ----------
        logger.log("\n----------读取初始DTC信息----------")
        request = [SID_19, 0x02, 0xFF]   # 0x19 02 FF：按状态掩码读取 DTC（所有状态）
        logger.log(f"请求: {bytes(request).hex().upper()}")
        resp = uds_request(uds_if, ECU_ADDR, TESTER_ADDR, request,
                           expected_positive_sid=SID_19 + 0x40, allow_nrc=True)
        if resp is None:
            logger.log("初始 DTC 读取失败（无响应或否定响应）", is_error=True)
        else:
            logger.log("初始 DTC 读取成功")

        # ---------- 清除 DTC ----------
        logger.log("\n----------清除DTC----------")
        request = [SID_14, SUB_DTCCLEAN_SESSION, 0xFF, 0xFF]   # 0x14 FF FF FF：清除所有 DTC
        logger.log(f"请求: {bytes(request).hex().upper()}")
        resp = uds_request(uds_if, ECU_ADDR, TESTER_ADDR, request,
                           expected_positive_sid=SID_14 + 0x40, allow_nrc=True)
        if resp is None:
            logger.log("清除 DTC 失败（无响应或否定响应）", is_error=True)
        else:
            logger.log("清除 DTC 成功")

        # ---------- 再次读取 DTC（验证清除效果）----------
        logger.log("\n----------清除后读取DTC信息----------")
        request = [SID_19, 0x02, 0xFF]
        logger.log(f"请求: {bytes(request).hex().upper()}")
        resp = uds_request(uds_if, ECU_ADDR, TESTER_ADDR, request,
                           expected_positive_sid=SID_19 + 0x40, allow_nrc=True)
        if resp is None:
            logger.log("清除后读取 DTC 失败（无响应或否定响应）", is_error=True)
        else:
            # 如果响应数据很短（例如只有状态字节）或无 DTC，则认为清除成功
            if resp.data and len(resp.data) <= 4:   # 0x19 02 FF 的典型空响应为 0x59 02 00
                logger.log("DTC 清除成功：无故障码存在")
                test_passed = True
            else:
                logger.log("DTC 清除后仍有故障码存在", is_error=True)

    except Exception as e:
        logger.log(f"主流程发生异常: {e}", is_error=True)
    finally:
        # 清理资源
        if uds_if is not None:
            uds_if = None
        if zxdoc is not None:
            zxdoc.disconnect()
            logger.log("ZXDoc 连接已断开")

        logger.log("\n===== 最终结果 =====")
        logger.log("✓ PASS" if test_passed else "✗ FAIL", is_error=not test_passed)
        logger.log(f"日志文件: {logger.log_path}")

if __name__ == "__main__":
    main()