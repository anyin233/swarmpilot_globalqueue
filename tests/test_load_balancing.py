#!/usr/bin/env python3
"""
测试 GlobalMsgQueue 的负载均衡功能
验证任务是否会被分发到预期时间最短的队列
"""
from main import SwarmPilotGlobalMsgQueue, GlobalRequestMessage
from uuid import uuid4
from loguru import logger
import time

def main():
    logger.info("=== 测试 GlobalMsgQueue 负载均衡 ===")

    # 1. 初始化 GlobalMsgQueue
    queue = SwarmPilotGlobalMsgQueue()
    queue.load_task_instance_from_config("task_instances.yaml")

    # 等待模型完全启动
    logger.info("等待模型完全启动...")
    time.sleep(3)

    # 2. 更新队列信息
    queue.update_queues()

    # 3. 发送多个任务，观察负载均衡
    logger.info("\n=== 发送 10 个任务测试负载均衡 ===")
    for i in range(10):
        test_task = GlobalRequestMessage(
            model_id="easyocr",
            input_features={
                "metadata": {
                    "hardware": "GPU_RTX_A6000",
                    "image_width": 1920,
                    "image_height": 1080,
                    "long_side": 1920
                }
            },
            uuid=uuid4()
        )

        response = queue.enqueue(test_task)
        logger.info(f"Task {i+1}: 入队到端口 {response.task_id}, 队列大小: {response.queue_size}")

    # 4. 查看最终的队列状态
    logger.info("\n=== 最终队列状态 ===")
    queue.update_queues()

    for model_name, pq in queue.queues.items():
        logger.info(f"\n模型: {model_name}")
        temp_list = []
        while not pq.empty():
            temp_list.append(pq.get())

        # 按端口排序以便查看
        temp_list.sort(key=lambda x: x.port)

        for q_obj in temp_list:
            logger.info(
                f"  Port {q_obj.port}: "
                f"队列长度={q_obj.length}, "
                f"预期时间={q_obj.expected_ms:.2f}ms, "
                f"误差={q_obj.error_ms:.2f}ms"
            )
            pq.put(q_obj)  # 放回队列

    logger.info("\n=== 测试完成 ===")
    logger.info("观察: 任务应该被均匀分配到三个实例，每个实例的队列长度应该接近")

if __name__ == "__main__":
    main()
