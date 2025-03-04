import os
import json
import logging
import boto3
from kubernetes import client, config

# 初始化日志
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def get_argocd_apps():
    try:
        config.load_incluster_config()
        v1 = client.CustomObjectsApi()
        # 记录 API 请求参数
        logging.debug(f"Requesting ArgoCD apps with: group=argoproj.io, version=v1alpha1, plural=applications")
        apps = v1.list_cluster_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            plural="applications"
        )
        # 记录响应数据摘要
        logging.info(f"API response items count: {len(apps.get('items', []))}")
        return apps.get("items", [])
    except Exception as e:
        logging.error(f"Failed to get ArgoCD apps: {e}", exc_info=True)  # 输出完整堆栈信息
        return []

def update_eventbridge_rules(repos):
    events = boto3.client("events", region_name=os.getenv("AWS_REGION"))
    
    # 1. 获取所有当前由 Lambda 管理的规则（名称前缀为 argocd-ecr-）
    existing_rules = events.list_rules(NamePrefix="argocd-ecr-")["Rules"]
    existing_rule_names = {rule["Name"] for rule in existing_rules}
    
    # 2. 生成当前需要的规则名称
    required_rule_names = {f"argocd-ecr-{repo.replace('/', '-')}" for repo in repos}
    
    # 3. 删除多余的旧规则（仓库已从 ArgoCD 中移除）
    for rule_name in existing_rule_names - required_rule_names:
        # 删除规则前需先移除其目标
        targets = events.list_targets_by_rule(Rule=rule_name)["Targets"]
        if targets:
            events.remove_targets(Rule=rule_name, Ids=[t["Id"] for t in targets])
        events.delete_rule(Name=rule_name)
        logging.info(f"Deleted old rule: {rule_name}")
    
    # 4. 创建或更新需要的规则
    for repo in repos:
        rule_name = f"argocd-ecr-{repo.replace('/', '-')}"
        event_pattern = {
            "source": ["aws.ecr"],
            "detail-type": ["ECR Image Action"],
            "detail": {"action-type": ["PUSH"], "repository-name": [repo]}
        }
        # 创建或更新规则（PutRule 在存在时会覆盖）
        events.put_rule(
            Name=rule_name,
            EventPattern=json.dumps(event_pattern),
            State="ENABLED"
        )
        # 更新目标（PutTargets 会覆盖旧目标）
        events.put_targets(
            Rule=rule_name,
            Targets=[{"Id": "lambda-target", "Arn": os.getenv("LAMBDA_ARN")}]
        )
        logging.info(f"Updated rule: {rule_name}")

def trigger_argocd_sync(repo_name, image_tag):
    """触发 ArgoCD 同步"""
    argocd_api = f"{os.getenv('ARGOCD_API_URL', 'http://argocd-server.argocd.svc.cluster.local')}/api/v1/applications"
    token = os.getenv("ARGOCD_TOKEN")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 查找匹配的应用
    apps = get_argocd_apps()
    for app in apps:
        app_name = app["metadata"]["name"]
        for image in app["spec"].get("images", []):
            current_repo = image["image"].split("/")[-1].split(":")[0]
            if current_repo == repo_name:
                # 触发同步
                sync_url = f"{argocd_api}/{app_name}/sync"
                try:
                    response = requests.post(sync_url, headers=headers, timeout=10)
                    logging.info(f"Synced {app_name}: {response.status_code}")
                except Exception as e:
                    logging.error(f"Failed to sync {app_name}: {e}")

def handler(event, context):
    """处理 EventBridge 事件或定时触发规则更新"""
    if event.get("source") == "aws.ecr":
        # 处理 ECR 推送事件
        detail = event.get("detail", {})
        repo_name = detail.get("repository-name")
        image_tag = detail.get("image-tag")
        if repo_name and image_tag:
            trigger_argocd_sync(repo_name, image_tag)
        return {"status": "event_processed"}
    else:
        # 定期更新 EventBridge 规则
        apps = get_argocd_apps()
        repos = list(set(
            image["image"].split("/")[-1].split(":")[0]
            for app in apps for image in app["spec"].get("images", [])
        ))
        update_eventbridge_rules(repos)
        return {"status": "rules_updated"}

