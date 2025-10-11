# 第三阶段任务清单：清理和文档化

**预计时间**: 1-1.5小时
**优先级**: 🟢 中
**前置条件**: 第一和第二阶段已完成，所有测试通过

---

## 任务 3.1: 清理旧文件 (20分钟)

### ⚠️ 重要提醒
**在删除任何文件之前，必须确保：**
1. 新代码已完全实现所有功能
2. 所有测试已通过
3. 已创建 git commit 保存当前状态

### 3.1.1 备份检查
```bash
# 1. 创建清理前的备份
git add .
git commit -m "feat: complete refactoring before cleanup"

# 2. 创建备份分支（可选）
git branch backup-before-cleanup
```

### 3.1.2 删除旧版本核心文件
```bash
# 进入项目目录
cd /home/yanweiye/Project/swarmpilot/swarmpilot_globalqueue

# 删除旧版本主文件
rm api.py                  # 旧版 API（已被 src/scheduler/api.py 替代）
rm main.py                 # 旧版 GlobalQueue（已被 src/scheduler/core.py 替代）
rm strategy.py             # 旧版策略（已被 strategy_refactored.py 替代）
rm task_instance_client.py # 旧版客户端（已被 task_instance_client_refactored.py 替代）

# 删除旧版本重构文件（已移动到 src/）
rm scheduler.py                    # → src/scheduler/core.py
rm scheduler_api.py                # → src/scheduler/api.py
rm strategy_refactored.py          # → src/scheduler/strategies/*
rm task_instance_client_refactored.py  # → src/scheduler/client.py
rm lookup_predictor.py             # → src/scheduler/predictor.py

# 删除旧版本示例
rm example_custom_strategy.py      # → examples/custom_strategy.py

# 删除根目录的测试文件（已整合到 tests/）
rm test_scheduler_lookup.py        # 整合到 tests/test_integration.py
rm test_integration_lookup.py      # 整合到 tests/test_integration.py
```

### 3.1.3 验证删除
```bash
# 确保项目仍可正常导入
python3 -c "from src.scheduler import SwarmPilotScheduler; print('✓ Import successful')"

# 确保测试仍可运行
uv run pytest tests/ -v
```

---

## 任务 3.2: 更新配置文件 (15分钟)

### 3.2.1 更新 `pyproject.toml`
```toml
[project]
name = "swarmpilot-scheduler"
version = "2.0.0"
description = "SwarmPilot Scheduler - Task scheduling service for distributed TaskInstances"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.11.10",
    "httpx>=0.28.1",
    "loguru>=0.7.3",
    "pyyaml>=6.0.3",
    "fastapi>=0.115.6",
    "uvicorn>=0.34.0",
    "typer>=0.15.2",
    "requests>=2.32.3",
]

# ✅ 新增：包配置
[tool.setuptools]
packages = [{include = "scheduler", from = "src"}]

# ✅ 新增：脚本入口
[project.scripts]
scheduler = "scheduler.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.4.2",
    "pytest-asyncio>=1.2.0",
    "pytest-cov>=4.0.0",  # ✅ 新增：覆盖率工具
]
```

### 3.2.2 更新 `cli.py`
```python
#!/usr/bin/env python3
"""
GlobalQueue CLI Tool
"""
import typer
import uvicorn
# ... 其他导入

# ✅ 修改导入
# 从
# from scheduler_api import app

# 改为
from src.scheduler.api import app

# 其余代码保持不变
```

### 3.2.3 创建 `src/__init__.py`
```python
"""SwarmPilot Scheduler Package"""
```

---

## 任务 3.3: 整理文档 (30分钟)

### 3.3.1 移动现有文档到 docs/
```bash
# 已移动的文档
# ✓ Scheduler.md (已在 docs/)
# ✓ LOOKUP_PREDICTOR.md (需要移动)
# ✓ LOOKUP_PREDICTOR_TEST_REPORT.md (需要移动)

# 保留在根目录的文档
# ✓ README.md (将更新)
# ✓ REFACTORING.md (作为历史记录)
```

### 3.3.2 更新 README.md
创建全新的 README，包含：

````markdown
# SwarmPilot Scheduler

> 灵活的任务调度系统，用于在多个 TaskInstance 之间分发工作负载

**版本**: 2.0.0 | **状态**: ✅ 生产就绪

## ✨ 特性

- 🎯 **多策略调度**: 支持最短队列、轮询、加权、概率等策略
- 📊 **任务跟踪**: 完整的任务状态管理和查询
- ⚡ **高性能**: 集成 lookup predictor，毫秒级预测
- 🔌 **REST API**: 完整的 FastAPI 实现，符合 OpenAPI 规范
- 🧪 **测试完善**: >80% 测试覆盖率
- 📦 **易于扩展**: 基于策略模式，支持自定义调度逻辑

## 📦 安装

### 使用 uv（推荐）
```bash
uv sync
```

### 使用 pip
```bash
pip install -e .
```

## 🚀 快速开始

### 1. 启动调度器服务
```bash
# 使用默认配置
uvicorn src.scheduler.api:app --host 0.0.0.0 --port 8102

# 或使用 CLI
python cli.py start --port 8102 --config config.yaml
```

### 2. 注册 Task Instance
```bash
curl -X POST http://localhost:8102/ti/register \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 8100}'
```

### 3. 提交任务
```bash
curl -X POST http://localhost:8102/queue/submit \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "test_model",
    "task_input": {"prompt": "Hello"},
    "metadata": {}
  }'
```

### 4. 查询任务
```bash
curl "http://localhost:8102/task/query?task_id=<task_id>"
```

## 📖 使用示例

### Python API
```python
from src.scheduler import SwarmPilotScheduler
from src.scheduler.models import SchedulerRequest

# 创建调度器
scheduler = SwarmPilotScheduler()
scheduler.load_task_instances_from_config("config.yaml")

# 提交任务
request = SchedulerRequest(
    model_type="gpt-3.5",
    input_data={"prompt": "Hello, world!"},
    metadata={}
)

response = scheduler.schedule(request)
print(f"Task scheduled: {response.task_id}")
```

### 自定义策略
```python
from src.scheduler.strategies import BaseStrategy

class MyStrategy(BaseStrategy):
    def _select_from_candidates(self, candidates, request):
        # 你的选择逻辑
        return candidates[0]

    def update_queue(self, instance, request, response):
        # 队列状态更新逻辑
        pass

# 使用自定义策略
scheduler.strategy = MyStrategy(scheduler.taskinstances)
```

## 📚 文档

- [API 规范](docs/Scheduler.md)
- [Lookup Predictor](docs/LOOKUP_PREDICTOR.md)
- [开发指南](docs/REFACTORING_PROGRESS.md)
- [第二阶段任务](docs/PHASE2_TASKS.md)
- [第三阶段任务](docs/PHASE3_TASKS.md)

## 🧪 测试

```bash
# 运行所有测试
uv run pytest tests/ -v

# 生成覆盖率报告
uv run pytest tests/ --cov=src/scheduler --cov-report=html

# 运行特定测试
uv run pytest tests/test_api.py -v
```

## 🏗️ 项目结构

```
swarmpilot_globalqueue/
├── src/scheduler/          # 核心包
│   ├── core.py             # 调度器核心
│   ├── api.py              # FastAPI 应用
│   ├── models.py           # 数据模型
│   ├── task_tracker.py     # 任务跟踪
│   ├── client.py           # TaskInstance 客户端
│   ├── predictor.py        # Lookup 预测器
│   └── strategies/         # 调度策略
├── tests/                  # 测试
├── examples/               # 示例代码
└── docs/                   # 文档
```

## 🔧 配置

### 配置文件示例 (`config.yaml`)
```yaml
instances:
  - host: localhost
    port: 8100
  - host: localhost
    port: 8101
```

### 环境变量
- `SCHEDULER_CONFIG_PATH`: 默认配置文件路径
- `LOG_LEVEL`: 日志级别（默认: INFO）

## 🤝 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

## 📄 许可证

MIT License

## 🙏 致谢

感谢所有贡献者和 SwarmPilot 项目。
````

### 3.3.3 创建 API 文档链接
在 `docs/API.md` 创建 API 快速参考（链接到 Scheduler.md）

---

## 任务 3.4: 最终验证 (15分钟)

### 3.4.1 功能验证清单
```bash
# 1. 导入测试
python3 -c "from src.scheduler import SwarmPilotScheduler; print('✓ Import OK')"

# 2. 单元测试
uv run pytest tests/ -v
# 预期: All tests pass

# 3. API 启动测试
uvicorn src.scheduler.api:app --host 127.0.0.1 --port 8102 &
sleep 2
curl http://127.0.0.1:8102/health
# 预期: {"status":"healthy",...}
kill %1

# 4. 示例代码测试
python3 examples/basic_usage.py
# 预期: 正常执行无错误
```

### 3.4.2 代码质量检查
```bash
# 检查导入循环
python3 -c "import sys; sys.path.insert(0, 'src'); import scheduler"

# 检查类型提示（如果使用 mypy）
# mypy src/scheduler/

# 检查代码风格（如果使用 black）
# black --check src/
```

### 3.4.3 文档完整性检查
- [ ] README.md 包含所有必要信息
- [ ] docs/ 目录结构清晰
- [ ] API 端点有完整文档
- [ ] 示例代码可运行
- [ ] 代码有充分注释

---

## 任务 3.5: 创建发布 (10分钟)

### 3.5.1 Git 提交
```bash
# 1. 查看所有更改
git status

# 2. 添加所有新文件
git add src/ tests/ examples/ docs/
git add pyproject.toml cli.py README.md

# 3. 创建提交
git commit -m "feat: complete scheduler v2.0 refactoring

- Restructure code to src/scheduler/ package
- Add TaskTracker for task state management
- Split strategies into separate modules
- Implement all Scheduler.md API endpoints
- Add comprehensive unit tests (>80% coverage)
- Create examples and documentation
- Clean up old files

BREAKING CHANGE: Import paths changed from root to src.scheduler"

# 4. 创建标签
git tag -a v2.0.0 -m "Release v2.0.0 - Complete refactoring"
```

### 3.5.2 推送到远程（如果需要）
```bash
git push origin master
git push origin v2.0.0
```

---

## 验收标准

### 代码清理
- [ ] 所有旧文件已删除
- [ ] 项目目录整洁
- [ ] 无未使用的导入
- [ ] 无调试代码残留

### 配置
- [ ] pyproject.toml 正确配置包信息
- [ ] cli.py 导入路径正确
- [ ] 环境变量文档完整

### 文档
- [ ] README.md 完整且格式正确
- [ ] 所有文档移动到 docs/
- [ ] API 文档完整
- [ ] 示例代码有注释

### 验证
- [ ] 所有测试通过
- [ ] 可以正常启动 API 服务
- [ ] 示例代码可运行
- [ ] Git 历史清晰

---

## 常见问题

### Q: 删除文件后出现导入错误怎么办？
A: 检查是否有代码仍在使用旧的导入路径：
```bash
grep -r "from scheduler import" .
grep -r "from strategy_refactored" .
```

### Q: 如何恢复误删的文件？
A: 使用 git 恢复：
```bash
git checkout HEAD -- <filename>
```

### Q: 测试失败怎么办？
A: 不要继续清理，先修复测试：
1. 查看失败的测试
2. 修复代码或测试
3. 确保所有测试通过
4. 再继续清理

---

## 完成后续步骤

### 1. 部署准备
- 更新部署脚本
- 更新 Docker 配置（如果有）
- 更新 CI/CD 流水线

### 2. 团队沟通
- 通知团队成员新的导入路径
- 分享 README 和文档
- 组织代码 review

### 3. 监控
- 部署后监控日志
- 检查性能指标
- 收集用户反馈

---

**🎉 恭喜！完成所有三个阶段后，你将拥有一个结构清晰、测试完善、文档齐全的调度器系统！**
