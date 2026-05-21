# -*- coding: utf-8 -*-
import os
import datetime
import time
from ZXDoc import ZXDoc, ZDoCANCfg, ZUdsRequest, ZUdsPort, ZCANFrameType, ZCANTpVersion, ZErrorCode

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ==================== 配置参数 ====================
CHANNEL_INDEX = 1          # 激活的 CAN 通道索引
TESTER_ADDR = 0x7BA        # 诊断仪地址（响应 ID）
ECU_ADDR = 0x7E          # ECU 地址（请求 ID）

# UDS 服务 ID
SID_10 = 0x10
SID_28 = 0x28
SID_NR = 0x7F

# 子功能
SUB_EXTENDED_SESSION = 0x01
SUB_DIAGNOSTIC = 0x80
SUB_DTC_OFF = 0x02
SUB_DISABLE_RX_TX = 0x03

# 例程 ID（2 字节）
ROUTINE_ID = [0x01, 0x03]

# DID 和测试数据
#DID_HIGH = 0xF1
#DID_LOW = 0x84
#WRITE_DATA = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]

P2_TIMEOUT_MS = 3000
P2X_TIMEOUT_MS = 4000

# ==================== 日志类 ====================
class TestLogger:
    def __init__(self):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(os.getcwd(), f"UDS_TestLog-通用流程-01-037_{timestamp}.txt")
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
def uds_request(uds_if, req_addr, rsp_addr, request_bytes, expected_positive_sid=None, allow_nrc=False):
    """发送 UDS 请求并返回响应对象或 None"""
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
        # 按用户要求：显示服务 ID 和数据
        logger.log(f"正响应: SID=0x{resp.sid:02X} Data={resp.data.hex().upper()}")
        return resp
    elif resp.responseType == 0:  # Negative
        logger.log(f"否定响应: NRC=0x{resp.NRC:02X}", is_error=not allow_nrc)
        if allow_nrc:
            return resp
        else:
            return None
    else:
        logger.log(f"未知响应类型: {resp.responseType}", is_error=True)
        return None

# ==================== 主流程 ====================
def main():
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
        zxdoc.disconnect()
        return
    logger.log("DoCAN 接口创建成功")


    logger.log("\n----------10 01功能寻址进入默认模式（7E）----------")
    request = [SID_10, SUB_EXTENDED_SESSION]
    logger.log(f"请求: {bytes(request).hex().upper()} ")

    resp = uds_request(uds_if, ECU_ADDR, TESTER_ADDR, request,
                       expected_positive_sid=SID_10 + 0x40, allow_nrc=True)


    if resp is None:
        logger.log("无响应 -> 成功")
        test_passed = True
    elif resp.responseType == 0:
        logger.log(f"收到否定响应: NRC=0x{resp.NRC:02X} -> 失败", is_error=True)
        test_passed = False
    else:
        logger.log("收到意外肯定响应 -> 失败", is_error=True)
        test_passed = False


    # 清理
    uds_if = None
    zxdoc.disconnect()

    logger.log("\n===== 最终结果 =====")
    logger.log("✓ PASS" if test_passed else "✗ FAIL", is_error=not test_passed)
    logger.log(f"日志文件: {logger.log_path}")

if __name__ == "__main__":
    main()