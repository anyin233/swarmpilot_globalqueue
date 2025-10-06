# Queue Design

Global Queue是一个全局分发工具，其在接到外部请求后立即将该请求按照一定的条件发送到一个指定的Task Instance上

## 与Task Instance对接

Task Instance上存在数个消息队列，每个消息队列对应一个model instance，使用端口号进行识别，可以通过`/model/list`获得模型和端口号的对应关系，使用`/mqueue/predict`获取整个队列的长度、预期计算时间和误差信息。

## 优先队列设计

Global Queue上存在数个优先队列，每个优先队列对应一个模型名称，与Task Instance中的模型信息对应。

### 优先队列结构

每个优先队列内部维护当前模型所对应的所有Task Instance队列信息，具体包括：

- **队列元素**: Task Instance的队列引用（包含地址和端口号）
- **优先级指标**: 预期执行时间（从`/mqueue/predict`获取）
- **排序策略**: 按预期执行时间升序排列（时间最短的队列优先级最高）
- **辅助信息**: 队列长度和预测误差

### 工作流程

1. **队列更新**: 定期通过`/mqueue/predict`更新各Task Instance队列的预期执行时间
2. **请求分发**: 当接收到模型请求时，从对应模型的优先队列中选择预期执行时间最短的Task Instance
3. **负载均衡**: 通过动态优先级调整实现智能负载均衡

### 优先队列实现

- 使用Python `heapq`模块或`queue.PriorityQueue`实现最小堆
- 优先级键值为预期执行时间
- 支持动态更新优先级（通过重新插入机制）

