# Stand3D pipeline

入口：[pipeline.py](pipeline.py)。使用方法、输入格式、验收边界和切换／回退说明见 [模型处理流水线](../../docs/stand3d-pipeline.md)。

Python保留原生元数据及文件事务；generate.mjs使用当前产品手臂求解生成制作轨迹；accept.mjs通过当前产品引擎验收；server.mjs只提供每轮自有的回环地址服务。unity/中的探针独立重建Avatar并采样原Humanoid片段。profiles/记录来源哈希和制作策略，原始资产继续放在忽略的corpus目录。
