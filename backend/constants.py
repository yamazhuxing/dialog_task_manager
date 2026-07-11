SCENE_OPTIONS: list[tuple[str, str]] = [
    ("development", "软件开发与工程"),
    ("system_admin", "系统运维与管理"),
    ("data_analysis", "数据分析与建模"),
    ("research", "研究与信息检索"),
    ("content_creation", "内容与文案创作"),
    ("communication", "通信与消息管理"),
    ("media_processing", "多媒体内容处理"),
    ("automation", "工作流与智能体编排"),
    ("monitoring", "系统监控与诊断"),
    ("scheduling", "日程与任务管理"),
    ("knowledge_mgmt", "知识与记忆管理"),
    ("finance", "金融与量化交易"),
    ("crm", "客户与业务运营"),
]

SCENE_LABELS = dict(SCENE_OPTIONS)

MIN_TASK_TURNS = 5
MAX_TASK_TURNS = 10
