# HTTP API 文档

## 概述
本项目提供基于 FastAPI 的 HTTP API，用于管理 Docker 模型服务和任务队列预测。

Base URL: `http://localhost:<port>` （默认端口根据服务配置而定）

---

## 1. 系统信息 API

### 1.1 获取系统信息

**Path:** `GET /info`

**功能:** 获取当前机器的GPU信息，包括GPU数量和名称

**输入:** 无

**输出 (200):**
```json
{
  "gpu_count": 2,
  "gpu_names": [
    "NVIDIA GeForce RTX 3090",
    "NVIDIA GeForce RTX 3090"
  ]
}
```

**说明:**
- 使用 `nvidia-smi` 检测系统GPU信息
- 若系统无GPU或nvidia-smi不可用，返回 `gpu_count: 0` 和空的 `gpu_names` 列表

---

## 2. 模型管理 API

### 2.1 启动模型服务

**Path:** `POST /model/start`

**功能:** 启动指定的 Docker 模型服务

**输入:**
```json
{
  "model": "string",        // 必填：模型名称，对应 docker/<model> 目录
  "num_gpus": 2,            // 可选：所需 GPU 数量，默认为 0
  "config": {               // 可选：启动配置
    "port": 8000,           // 期望端口号（若被占用将自动分配新端口）
    "env": {                // 环境变量
      "HOST_PORT": "8000"
    },
    "args": ["--flag"]      // 命令行参数
  }
}
```

**端口分配规则:**
- 若请求的端口可用，则使用该端口
- 若请求的端口被占用，从请求端口+1开始搜索可用端口
- 若未找到，从 8000 开始搜索可用端口
- 分配的实际端口号将通过 `HOST_PORT` 环境变量传递给容器

**输出 (202):**
```json
{
  "detail": "Started docker script for model 'sglang'.",
  "pid": 12345,
  "command": ["/path/to/start_docker.sh", "--port", "8000"],
  "working_dir": "/path/to/docker/sglang",
  "port": 8001,             // 实际分配的端口号（可能与请求端口不同）
  "gpu_ids": [0, 1]         // 分配的 GPU 序号列表（num_gpus=0 时为 null）
}
```

**错误码:**
- `400`: 模型名称无效或为空、num_gpus 为负数
- `404`: 找不到对应的 `start_docker.sh` 脚本
- `409`: 模型已在启动或运行中
- `500`: 启动失败
- `503`: GPU 资源不足或无可用端口

---

### 2.2 停止模型服务

**Path:** `POST /model/stop`

**功能:** 根据模型名称和端口号停止指定的模型服务，并释放占用的GPU资源

**输入:**
```json
{
  "model": "sglang",        // 必填：要停止的模型名称
  "port": 8002              // 必填：模型运行的端口号
}
```

**输出 (200):**
```json
{
  "detail": "Stopped model 'sglang' on port 8002."
}
```

**错误码:**
- `400`: 模型名称无效、端口范围错误、或端口号与实际运行端口不匹配
- `404`: 模型未运行或不存在
- `500`: 停止失败

**说明:**
- 必须同时提供正确的模型名称和端口号才能停止模型
- 停止时会自动释放该模型占用的GPU资源
- 若端口号与模型实际运行端口不匹配，将返回错误

---

### 2.3 停止所有模型服务

**Path:** `POST /model/stop_all`

**功能:** 停止所有当前正在运行的模型服务，并释放所有占用的GPU资源

**输入:** 无

**输出 (200):**
```json
{
  "detail": "Stopped 2 model(s).",
  "stopped": [
    {
      "model": "sglang",
      "port": 8002
    },
    {
      "model": "easyocr",
      "port": 8000
    }
  ],
  "errors": [],
  "total_stopped": 2,
  "total_errors": 0
}
```

**当出现部分失败时 (200):**
```json
{
  "detail": "Stopped 1 model(s).",
  "stopped": [
    {
      "model": "sglang",
      "port": 8002
    }
  ],
  "errors": [
    {
      "model": "easyocr",
      "port": 8000,
      "error": "Failed to stop docker resources: ..."
    }
  ],
  "total_stopped": 1,
  "total_errors": 1
}
```

**当没有活跃模型时 (200):**
```json
{
  "detail": "No active models to stop.",
  "stopped": [],
  "errors": [],
  "total_stopped": 0,
  "total_errors": 0
}
```

**说明:**
- 停止所有处于活跃状态（starting、running、stopping）的模型
- 按启动顺序（STARTED_MODELS列表）依次停止
- 每个模型停止时会自动释放其占用的GPU资源
- 即使部分模型停止失败，也会继续尝试停止其他模型
- 返回成功停止的模型列表和失败的模型列表
- 该操作总是返回 200 状态码，通过响应体中的 `stopped` 和 `errors` 字段来判断具体结果

---

### 2.4 查询模型状态

**Path:** `GET /model/status/{model_name}`

**功能:** 查询指定模型的运行状态

**输入:**
- Path 参数: `model_name` (string) - 模型名称

**输出 (200):**
```json
{
  "model": "sglang",
  "status": "running",      // 状态: not_started | starting | running | stopping | stopped | error
  "port": 8002,
  "pid": 12345,
  "command": ["/path/to/start_docker.sh"],
  "working_dir": "/path/to/docker/sglang",
  "error": null,            // 错误信息（仅在 status=error 时）
  "gpu_ids": [0, 1]         // 分配的 GPU 序号列表（未分配时为 null）
}
```

**错误码:**
- `400`: 模型名称无效
- `404`: 找不到对应的模型脚本

---

### 2.5 列出已启动的模型

**Path:** `GET /model/list`

**功能:** 列出所有当前已启动的活跃模型及其端口号

**输入:** 无

**输出 (200):**
```json
{
  "models": [
    {
      "model": "sglang",
      "port": 8002,
      "gpu_ids": [0, 1]
    },
    {
      "model": "easyocr",
      "port": 8000,
      "gpu_ids": null
    }
  ]
}
```

**说明:**
- 仅返回处于活跃状态（starting、running、stopping）的模型
- 按启动顺序排列

---

## 3. 任务队列 API

**重要说明：** 从 v3.0 开始，任务入队大幅简化。系统通过端口自动推断模型类型和配置，用户只需提供业务相关的 metadata。

### 3.1 任务入队

**Path:** `POST /mqueue/enqueue`

**功能:** 将任务添加到指定端口的预测队列

**输入:**
```json
{
  "port": 8000,             // 必填：目标模型实例的端口号（1-65535）
  "task": {
    "input_data": {},       // 可选：任务输入数据
    "metadata": {           // 必填：任务相关元数据（仅业务字段）
      "hardware": "NVIDIA GeForce RTX 3090",

      // OCR 任务必填字段:
      "image_width": 1920,
      "image_height": 1080,
      "long_side": 1920,

      // LLM 任务必填字段:
      // "input_tokens": 100,
      // "temperature": 0.7,
      // "top_p": 0.9,
      // "top_k": 50,

      // 可选字段:
      "duration_ms": 123.45,
      "request_id": "req-123",
      "timestamp": "2025-01-01T00:00:00Z",
      "hardware_info": {},
      "execution_profile": {},
      "hardware_params": []
    }
  }
}
```

**自动推断的字段（从模型注册表）:**
- `task_type`: 根据端口对应的模型自动填充（如 "ocr"、"llm"、"flux_image"）
- `model_id`: 从注册表获取（如 "ocr_easyocr"）
- `model_name`: 从注册表获取（如 "easyocr"）
- `software_name`: 从注册表获取（如 "easyocr"）
- `software_version`: 从注册表获取（如 "1.7.1"）
- 队列配置（`queue_config`）: 从注册表中该模型的默认配置获取

**输出 (200):**
```json
{
  "detail": "Task enqueued.",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "port": 8000,             // 任务所在队列的端口号
  "queue_size": 5           // 该端口队列的当前长度
}
```

**错误码:**
- `400`: 请求格式错误、缺少 port 字段、端口范围错误、缺少必填元数据字段
- `404`: 端口未注册模型（需要先启动模型）
- `500`: 模型配置未在注册表中找到

**说明:**
- ⚠️ **重大变更（v3.0）**: 任务不再需要提供 `task_type`、`model_id`、`model_name` 等模型相关字段
- 系统通过 `port` 自动从模型注册表获取所有模型信息
- 用户只需提供业务相关的 `metadata`（如图像尺寸、输入 tokens 等）
- 队列配置现在从模型注册表的 `queue_config` 中获取
- 队列在首次接收任务时自动创建，使用注册表中的默认配置

---

### 3.2 队列预测

**Path:** `POST /mqueue/predict`

**功能:** 对指定端口队列中的所有任务进行执行时间预测

**输入:**
```json
{
  "port": 8000,             // 必填：目标队列的端口号（1-65535）
  "clear_queue": false      // 可选：预测后是否清空队列（默认 false）
}
```

**说明（v3.0 变更）:**
- ⚠️ `queue_options` 字段已移除，队列配置现在从模型注册表自动获取
- 预测使用的配置来自模型启动时从注册表加载的 `queue_config`

**输出 (200):**
```json
{
  "expected_ms": 1234.56,   // 队列总预期执行时间（毫秒）
  "error_ms": 89.12,        // 预测误差范围（毫秒）
  "tasks": [                // 每个任务的预测详情
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "quantiles": {
        "0.25": 1000.0,
        "0.5": 1200.0,
        "0.75": 1400.0,
        "0.99": 2000.0
      },
      "distribution_summary": {
        "expected_ms": 1210.0,
        "error_ms": 45.3
      }
    }
  ],
  "port": 8000,             // 预测的队列端口号
  "queue_size": 5,          // 预测时的队列长度
  "cleared": false          // 是否已清空队列
}
```

**错误码:**
- `400`: 请求格式错误、缺少 port 字段、端口范围错误
- `404`: 指定端口的队列未初始化或为空
- `502`: 预测服务调用失败

**说明:**
- 只对指定端口的队列进行预测，不影响其他端口的队列
- 如果 `clear_queue=true`，仅清空该端口的队列
- 预测配置来自模型注册表中的 `queue_config`，无法在预测时修改

---

### 3.3 查询队列状态

**Path:** `GET /mqueue/status/{port}`

**功能:** 查询指定端口队列的状态和配置信息

**输入:**
- Path 参数: `port` (integer) - 队列端口号（1-65535）

**输出 (200):**
```json
{
  "port": 8000,
  "queue_size": 5,          // 当前队列中的任务数量
  "model_id": "ocr_easyocr", // 该端口对应的模型 ID（从模型注册表获取）
  "options": {              // 该队列的配置选项
    "prediction_type": "distribution",
    "confidence_level": 0.95,
    "no_enhanced_extractor": true,
    "base_url": "http://localhost:8000",
    "timeout": 10.0
  }
}
```

**错误码:**
- `400`: 端口范围错误
- `404`: 指定端口没有对应的队列

**说明:**
- 返回队列的实时状态和配置信息
- `model_id` 字段根据端口-模型映射关系自动填充

---

### 3.4 列出所有队列

**Path:** `GET /mqueue/list`

**功能:** 列出当前所有活跃的消息队列及其状态

**输入:** 无

**输出 (200):**
```json
{
  "queues": [
    {
      "port": 8000,
      "queue_size": 5,
      "model_id": "ocr_easyocr"
    },
    {
      "port": 8002,
      "queue_size": 3,
      "model_id": "llm_sglang"
    },
    {
      "port": 8003,
      "queue_size": 0,
      "model_id": "flux_image_gen"
    }
  ],
  "total_queues": 3         // 当前活跃的队列总数
}
```

**说明:**
- 返回所有已创建的队列，即使队列为空也会显示
- 队列按端口号排序
- 当模型停止时，对应端口的队列会被自动清理

---

## 4. 模型注册表

### 4.1 配置文件

**文件路径:** `docker/model_registry.yaml`

**功能:** 定义模型的完整配置，包括类型、元数据和队列配置

**格式（v3.0）:**
```yaml
models:
  ocr_easyocr:
    docker_dir: easyocr
    default_port: 8000
    task_type: ocr
    model_name: easyocr
    software_name: easyocr
    software_version: "1.7.1"
    queue_config:
      prediction_type: distribution
      confidence_level: 0.95
      no_enhanced_extractor: true
      base_url: "http://localhost:8000"
      timeout: 10.0

  llm_sglang:
    docker_dir: sglang
    default_port: 8002
    task_type: llm
    model_name: llama-8b
    software_name: sglang
    software_version: "0.4.6"
    queue_config:
      prediction_type: distribution
      confidence_level: 0.95
      no_enhanced_extractor: true
      base_url: "http://localhost:8000"
      timeout: 10.0

  flux_image_gen:
    docker_dir: flux
    default_port: null
    task_type: flux_image
    model_name: flux
    software_name: flux
    software_version: "1.0"
    queue_config:
      prediction_type: distribution
      confidence_level: 0.95
      no_enhanced_extractor: true
      base_url: "http://localhost:8000"
      timeout: 10.0
```

**字段说明:**
- `models`: 模型配置字典
  - `<model_id>`: 模型唯一标识符
    - `docker_dir`: 对应的 Docker 目录名称
    - `default_port`: 默认端口号（可为 null）
    - **`task_type`**: ⭐ 任务类型（用于自动推断）
    - **`model_name`**: ⭐ 模型名称（自动填充到任务）
    - **`software_name`**: ⭐ 软件名称（自动填充到任务）
    - **`software_version`**: ⭐ 软件版本（自动填充到任务）
    - **`queue_config`**: ⭐ 队列配置（用于 predictor API）
      - `prediction_type`: 预测类型
      - `confidence_level`: 置信水平
      - `no_enhanced_extractor`: 是否禁用增强提取器
      - `base_url`: Predictor 服务地址
      - `timeout`: 请求超时时间

**说明:**
- ⚠️ **v3.0 重大变更**: 注册表现在包含模型的完整配置信息
- 系统根据此配置文件建立端口到 model_id 的映射关系
- 当模型启动时，系统会查找对应的 model_id 并注册到端口映射表
- 任务入队时，系统自动从注册表提取 `task_type` 和模型元数据
- 队列创建时，系统自动从注册表提取 `queue_config`
- 用户无需在任务中提供这些信息，大幅简化了 API 使用

---

## 5. 数据模型

### 5.1 TaskType（任务类型）

**⚠️ 重大变更（v2.0）:** TaskType 不再是枚举类型，现在接受任意字符串。

**支持的任务类型示例:**
- `"ocr"`: OCR（光学字符识别）任务
- `"llm"`: LLM（大语言模型）任务
- `"flux_image"`: Flux 图像生成任务
- 或任何其他自定义字符串

**说明:**
- 任务类型现在完全由用户定义，系统不再限制特定的枚举值
- 不同任务类型可能需要不同的元数据字段（参见任务入队 API）
- 系统会根据任务类型的字符串值（小写）查找对应的元数据验证规则

### 5.2 模型状态
- `not_started`: 未启动
- `starting`: 启动中
- `running`: 运行中
- `stopping`: 停止中
- `stopped`: 已停止
- `error`: 错误

### 5.3 queue_options 字段说明
- `prediction_type` (string): 预测类型，默认 `"distribution"`
- `confidence_level` (float): 置信水平，范围 0.0-1.0，默认 `0.95`
- `no_enhanced_extractor` (bool): 是否禁用增强提取器，默认 `true`
- `base_url` (string): 预测服务的基础 URL，默认 `"http://localhost:8000"`
- `timeout` (float): 请求超时时间（秒），默认 `10.0`

---

## 6. 注意事项

### 6.1 模型管理
1. **模型名称规范**: 模型名称不能包含 `/`、`\`、`..` 等路径遍历字符
2. **Docker 权限**: 服务启动时会验证 Docker 守护进程访问权限
3. **端口管理**:
   - 系统自动检测端口可用性，若请求端口被占用则自动分配替代端口
   - 端口分配策略：优先使用请求端口 → 请求端口+1开始搜索 → 从8000开始搜索
   - 最终分配的端口号通过 `HOST_PORT` 环境变量传递给容器
   - 响应中的 `port` 字段为实际分配的端口号
4. **GPU 资源管理**:
   - 系统使用 `nvidia-smi` 自动检测可用 GPU 数量
   - GPU 资源按需分配，遵循先到先得原则
   - 当 GPU 资源不足时，启动请求将返回 503 错误
   - 模型停止时自动释放已分配的 GPU
   - 启动时通过环境变量 `CUDA_VISIBLE_DEVICES` 将分配的 GPU 传递给 Docker 容器
   - `num_gpus=0` 表示不需要 GPU（默认值）

### 6.2 队列管理（v2.0 新增）
1. **多队列架构**:
   - 每个模型实例（通过端口标识）维护独立的消息队列
   - 不同端口的队列相互隔离，互不影响
2. **队列配置一致性**:
   - 每个端口的队列在首次创建时确定配置
   - 后续对该端口队列的操作，`queue_options` 必须与初始值一致
3. **任务类型灵活性**:
   - `task_type` 现在接受任意字符串，不再限于预定义的枚举值
   - 不同 `task_type` 可能需要不同的必填元数据字段
   - 系统会根据任务类型字符串（转为小写后）查找对应的验证规则
4. **队列生命周期**:
   - 队列在首次接收任务时自动创建
   - 当对应的模型停止时，队列会被自动清理
   - 使用 `/mqueue/list` 可以查看所有活跃队列
5. **端口到模型映射**:
   - 系统维护端口到 model_id 的映射关系
   - 映射关系基于 `docker/model_registry.yaml` 配置文件
   - 模型启动时自动注册，停止时自动注销

### 6.3 迁移指南

#### 6.3.1 v1.x → v2.0

**破坏性变更:**
1. API 请求需要 `port` 参数
2. `task_type` 从枚举改为字符串

**迁移示例:**
```json
// v1.x
{
  "task": {"task_type": "ocr", ...}
}

// v2.0
{
  "port": 8000,
  "task": {"task_type": "ocr", ...}
}
```

#### 6.3.2 v2.0 → v3.0

**⚠️ 重大简化（v3.0）:**

1. **任务结构大幅简化**:
   - 移除 `task_type`、`model_id`、`model_name` 等模型相关字段
   - 这些信息现在从端口自动推断

2. **队列配置移至模型注册表**:
   - 移除 `/mqueue/enqueue` 和 `/mqueue/predict` 的 `queue_options` 参数
   - 配置现在从 `docker/model_registry.yaml` 获取

**迁移示例:**

```json
// v2.0 - 用户需要提供完整模型信息
{
  "port": 8000,
  "task": {
    "task_type": "ocr",
    "metadata": {
      "model_id": "ocr_easyocr",
      "model_name": "easyocr",
      "software_name": "easyocr",
      "software_version": "1.7.1",
      "hardware": "GPU",
      "image_width": 1920,
      "image_height": 1080,
      "long_side": 1920
    }
  },
  "queue_options": {
    "prediction_type": "distribution",
    "confidence_level": 0.95
  }
}

// v3.0 - 只需提供业务数据
{
  "port": 8000,
  "task": {
    "metadata": {
      "hardware": "GPU",
      "image_width": 1920,
      "image_height": 1080,
      "long_side": 1920
    }
  }
}
```

**迁移步骤:**
1. 更新 `docker/model_registry.yaml`，添加模型的完整配置
2. 从任务请求中移除 `task_type`、`model_id`、`model_name` 等字段
3. 从任务请求中移除 `queue_options`
4. 确保端口对应的模型已启动并注册

---

## 7. API 版本历史

### v3.0 (2025-10) - 当前版本

**重大简化：配置驱动的任务管理**

- ⭐ **任务入队大幅简化**: 移除 `task_type`、`model_id` 等模型相关字段，系统从端口自动推断
- ⭐ **配置集中管理**: 队列配置从 API 参数移至模型注册表
- ⭐ **增强的模型注册表**: 包含完整的模型元数据和队列配置
- 🔧 `_build_task_message` 现在接受 `port` 参数并自动填充模型信息
- 🔧 `_ensure_task_queue_locked` 从注册表加载队列配置
- 💥 **破坏性变更**: 任务中移除 `task_type` 字段（自动推断）
- 💥 **破坏性变更**: 移除 `/mqueue/enqueue` 和 `/mqueue/predict` 的 `queue_options` 参数
- 💥 **破坏性变更**: 任务中移除 `model_id`、`model_name`、`software_name`、`software_version` 字段（自动填充）

**优势:**
- 用户只需关注业务数据（如图像尺寸、输入tokens），无需了解模型配置
- 所有模型配置集中在 `docker/model_registry.yaml`，便于维护
- API 使用更简单，出错几率更低

### v2.0 (2025-10)

**多队列架构**

- ✨ 新增多队列管理架构，支持每个端口独立的消息队列
- ✨ 新增 `/mqueue/status/{port}` 端点，查询指定队列状态
- ✨ 新增 `/mqueue/list` 端点，列出所有活跃队列
- ✨ 新增模型注册表 `docker/model_registry.yaml`
- 🔧 `task_type` 从枚举改为字符串，支持自定义任务类型
- 💥 **破坏性变更**: `/mqueue/enqueue` 和 `/mqueue/predict` 需要 `port` 参数
- 💥 **破坏性变更**: TaskType 枚举已移除

### v1.x

**单队列版本**

- 初始版本
- 单一全局消息队列
- TaskType 枚举限定为 OCR 和 LLM
