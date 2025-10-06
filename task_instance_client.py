"""
Task Instance Client - Wrapper for Task Instance HTTP API
"""
import httpx
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field
from enum import Enum


# ========== Data Models ==========

# TaskType is now a plain string (v2.0 change)
# No longer using Enum - accepts any arbitrary string


class ModelStatus(str, Enum):
    """模型状态枚举"""
    NOT_STARTED = "not_started"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class PredictionType(str, Enum):
    """预测类型"""
    DISTRIBUTION = "distribution"


class GPUInfo(BaseModel):
    """GPU信息"""
    gpu_count: int
    gpu_names: List[str]


class ModelStartConfig(BaseModel):
    """模型启动配置"""
    port: Optional[int] = None
    env: Optional[Dict[str, str]] = None
    args: Optional[List[str]] = None


class ModelStartRequest(BaseModel):
    """模型启动请求"""
    model: str
    num_gpus: int = 0
    config: Optional[ModelStartConfig] = None


class ModelStartResponse(BaseModel):
    """模型启动响应"""
    detail: str
    pid: int
    command: List[str]
    working_dir: str
    port: int
    gpu_ids: Optional[List[int]] = None


class ModelStopRequest(BaseModel):
    """模型停止请求"""
    model: str
    port: int


class ModelStopResponse(BaseModel):
    """模型停止响应"""
    detail: str


class StoppedModel(BaseModel):
    """已停止的模型信息"""
    model: str
    port: int


class StopError(BaseModel):
    """停止错误信息"""
    model: str
    port: int
    error: str


class ModelStopAllResponse(BaseModel):
    """停止所有模型响应"""
    detail: str
    stopped: List[StoppedModel]
    errors: List[StopError]
    total_stopped: int
    total_errors: int


class ModelStatusResponse(BaseModel):
    """模型状态响应"""
    model: str
    status: ModelStatus
    port: Optional[int] = None
    pid: Optional[int] = None
    command: Optional[List[str]] = None
    working_dir: Optional[str] = None
    error: Optional[str] = None
    gpu_ids: Optional[List[int]] = None


class ModelInfo(BaseModel):
    """模型信息"""
    model: str
    port: int
    gpu_ids: Optional[List[int]] = None


class ModelListResponse(BaseModel):
    """模型列表响应"""
    models: List[ModelInfo]


class TaskMetadata(BaseModel):
    """
    任务元数据 (v3.0 - 仅包含业务相关字段)

    模型相关字段(model_id, model_name, software_name, software_version)
    现在由系统根据端口自动推断,不再需要用户提供
    """
    hardware: str

    # OCR任务必填字段
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    long_side: Optional[int] = None

    # LLM任务必填字段
    input_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None

    # 可选字段
    duration_ms: Optional[float] = None
    request_id: Optional[str] = None
    timestamp: Optional[str] = None
    hardware_info: Optional[Dict[str, Any]] = None
    execution_profile: Optional[Dict[str, Any]] = None
    hardware_params: Optional[List[Any]] = None


class Task(BaseModel):
    """
    任务定义 (v3.0 - task_type已移除)

    task_type字段已在v3.0中移除,系统根据端口自动推断任务类型
    """
    input_data: Optional[Dict[str, Any]] = None
    metadata: TaskMetadata


class QueueOptions(BaseModel):
    """队列配置选项"""
    prediction_type: PredictionType = PredictionType.DISTRIBUTION
    confidence_level: float = 0.95
    no_enhanced_extractor: bool = True
    base_url: str = "http://localhost:8000"
    timeout: float = 10.0


class EnqueueRequest(BaseModel):
    """
    入队请求 (v3.0)

    - port: 必填,指定目标模型实例的端口号
    - task: 任务数据(仅包含业务相关的metadata)
    - queue_options已移除,配置从模型注册表自动获取
    """
    port: int = Field(..., ge=1, le=65535, description="目标模型实例的端口号")
    task: Task


class EnqueueResponse(BaseModel):
    """入队响应 (v3.0 - 添加port字段)"""
    detail: str
    task_id: str
    port: int = Field(..., description="任务所在队列的端口号")
    queue_size: int


class PredictRequest(BaseModel):
    """
    预测请求 (v3.0)

    - port: 必填,指定目标队列的端口号
    - clear_queue: 可选,预测后是否清空队列
    - queue_options已移除,配置从模型注册表自动获取
    """
    port: int = Field(..., ge=1, le=65535, description="目标队列的端口号")
    clear_queue: bool = False


class DistributionSummary(BaseModel):
    """分布摘要"""
    expected_ms: float
    error_ms: float


class TaskPrediction(BaseModel):
    """任务预测详情"""
    task_id: str
    quantiles: Dict[str, float]
    distribution_summary: DistributionSummary


class PredictResponse(BaseModel):
    """预测响应 (v3.0 - 添加port字段)"""
    expected_ms: float
    error_ms: float
    tasks: List[TaskPrediction]
    port: int = Field(..., description="预测的队列端口号")
    queue_size: int
    cleared: bool


class QueueStatusResponse(BaseModel):
    """队列状态响应 (v2.0新增)"""
    port: int
    queue_size: int
    model_id: str = Field(..., description="该端口对应的模型ID")
    options: Dict[str, Any] = Field(..., description="队列配置选项")


class QueueInfo(BaseModel):
    """队列信息 (v2.0新增)"""
    port: int
    queue_size: int
    model_id: str


class QueueListResponse(BaseModel):
    """队列列表响应 (v2.0新增)"""
    queues: List[QueueInfo]
    total_queues: int


# ========== Task Instance Client ==========

class TaskInstanceClient:
    """
    Task Instance HTTP API 客户端

    用于与Task Instance服务进行通信，管理模型和任务队列。

    Args:
        base_url: Task Instance服务的基础URL，例如 "http://localhost:8000"
        timeout: 请求超时时间（秒），默认30秒
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        """
        初始化Task Instance客户端

        Args:
            base_url: Task Instance服务的基础URL
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def __enter__(self):
        """支持上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """关闭HTTP客户端"""
        self.close()

    def close(self):
        """关闭HTTP客户端连接"""
        self.client.close()

    # ========== 系统信息 API ==========

    def get_info(self) -> GPUInfo:
        """
        获取系统GPU信息

        Returns:
            GPUInfo: GPU数量和名称信息

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.get(f"{self.base_url}/info")
        response.raise_for_status()
        return GPUInfo(**response.json())

    # ========== 模型管理 API ==========

    def start_model(
        self,
        model: str,
        num_gpus: int = 0,
        config: Optional[ModelStartConfig] = None
    ) -> ModelStartResponse:
        """
        启动模型服务

        Args:
            model: 模型名称
            num_gpus: 所需GPU数量，默认为0
            config: 启动配置（端口、环境变量、命令行参数）

        Returns:
            ModelStartResponse: 启动响应，包含PID、实际端口号、GPU分配等信息

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        request_data = ModelStartRequest(
            model=model,
            num_gpus=num_gpus,
            config=config
        )
        response = self.client.post(
            f"{self.base_url}/model/start",
            json=request_data.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        return ModelStartResponse(**response.json())

    def stop_model(self, model: str, port: int) -> ModelStopResponse:
        """
        停止指定的模型服务

        Args:
            model: 模型名称
            port: 模型运行的端口号

        Returns:
            ModelStopResponse: 停止响应

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        request_data = ModelStopRequest(model=model, port=port)
        response = self.client.post(
            f"{self.base_url}/model/stop",
            json=request_data.model_dump()
        )
        response.raise_for_status()
        return ModelStopResponse(**response.json())

    def stop_all_models(self) -> ModelStopAllResponse:
        """
        停止所有模型服务

        Returns:
            ModelStopAllResponse: 停止结果，包含成功和失败的模型列表

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.post(f"{self.base_url}/model/stop_all")
        response.raise_for_status()
        return ModelStopAllResponse(**response.json())

    def get_model_status(self, model_name: str) -> ModelStatusResponse:
        """
        查询模型状态

        Args:
            model_name: 模型名称

        Returns:
            ModelStatusResponse: 模型状态信息

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.get(f"{self.base_url}/model/status/{model_name}")
        response.raise_for_status()
        return ModelStatusResponse(**response.json())

    def list_models(self) -> ModelListResponse:
        """
        列出所有活跃的模型

        Returns:
            ModelListResponse: 模型列表，包含模型名称、端口号和GPU分配

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.get(f"{self.base_url}/model/list")
        response.raise_for_status()
        return ModelListResponse(**response.json())

    # ========== 任务队列 API ==========

    def enqueue_task(
        self,
        port: int,
        task: Task
    ) -> EnqueueResponse:
        """
        将任务添加到指定端口的队列 (v3.0)

        Args:
            port: 目标模型实例的端口号
            task: 任务定义(仅包含业务相关的metadata)

        Returns:
            EnqueueResponse: 入队响应，包含任务ID、端口号和队列大小

        Raises:
            httpx.HTTPError: HTTP请求失败

        注意:
            - v3.0移除了queue_options参数,配置从模型注册表自动获取
            - task中不再需要task_type等模型相关字段,系统根据端口自动推断
        """
        request_data = EnqueueRequest(
            port=port,
            task=task
        )
        response = self.client.post(
            f"{self.base_url}/mqueue/enqueue",
            json=request_data.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        return EnqueueResponse(**response.json())

    def predict_queue(
        self,
        port: int,
        clear_queue: bool = False
    ) -> PredictResponse:
        """
        对指定端口队列中的任务进行执行时间预测 (v3.0)

        Args:
            port: 目标队列的端口号
            clear_queue: 预测后是否清空队列，默认False

        Returns:
            PredictResponse: 预测结果，包含总预期时间、误差、端口号和各任务详情

        Raises:
            httpx.HTTPError: HTTP请求失败

        注意:
            - v3.0移除了queue_options参数,配置从模型注册表自动获取
            - 只对指定端口的队列进行预测
        """
        request_data = PredictRequest(
            port=port,
            clear_queue=clear_queue
        )
        response = self.client.post(
            f"{self.base_url}/mqueue/predict",
            json=request_data.model_dump(exclude_none=True)
        )
        response.raise_for_status()
        return PredictResponse(**response.json())

    def get_queue_status(self, port: int) -> QueueStatusResponse:
        """
        查询指定端口队列的状态和配置信息 (v2.0新增)

        Args:
            port: 队列端口号

        Returns:
            QueueStatusResponse: 队列状态信息，包含队列大小、模型ID和配置

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.get(f"{self.base_url}/mqueue/status/{port}")
        response.raise_for_status()
        return QueueStatusResponse(**response.json())

    def list_queues(self) -> QueueListResponse:
        """
        列出所有活跃的消息队列 (v2.0新增)

        Returns:
            QueueListResponse: 队列列表，包含每个队列的端口、大小和模型ID

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        response = self.client.get(f"{self.base_url}/mqueue/list")
        response.raise_for_status()
        return QueueListResponse(**response.json())

    # ========== 便捷方法 ==========

    def get_queue_prediction_time(
        self,
        port: int
    ) -> tuple[float, float]:
        """
        获取指定端口队列的预期执行时间和误差 (v3.0更新)

        这是predict_queue的便捷方法，只返回时间信息

        Args:
            port: 队列端口号

        Returns:
            tuple[float, float]: (预期执行时间(ms), 误差(ms))

        Raises:
            httpx.HTTPError: HTTP请求失败
        """
        result = self.predict_queue(port=port, clear_queue=False)
        return result.expected_ms, result.error_ms

    def is_model_running(self, model_name: str) -> bool:
        """
        检查模型是否正在运行

        Args:
            model_name: 模型名称

        Returns:
            bool: True表示模型正在运行
        """
        try:
            status = self.get_model_status(model_name)
            return status.status == ModelStatus.RUNNING
        except httpx.HTTPError:
            return False
