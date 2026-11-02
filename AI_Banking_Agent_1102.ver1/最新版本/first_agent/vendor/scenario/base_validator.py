

from typing import Any, Dict, List, Tuple


def validate(
    scenario: Dict[str, Any],
    config: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """检查银行场景的基本结构和数据合理性。"""

    errors: List[str] = []

    # 1. 检查场景本身
    if not isinstance(scenario, dict):
        return False, ["场景数据不是有效的字典"]

    if not scenario:
        return False, ["场景数据为空"]

    # 2. 检查必要字段
    required_fields = [
        "scenario_id",
        "scenario_type",
        "user",
        "accounts",
        "transactions",
    ]

    for field in required_fields:
        if field not in scenario:
            errors.append(f"缺少必要字段：{field}")

    # 如果关键字段缺失，先停止后续检查
    if errors:
        return False, errors

    # 3. 检查用户信息
    if not isinstance(scenario["user"], dict):
        errors.append("user 必须是字典")
    elif not scenario["user"]:
        errors.append("用户信息不能为空")

    # 4. 检查账户列表
    accounts = scenario["accounts"]

    if not isinstance(accounts, list) or not accounts:
        errors.append("accounts 必须是非空列表")
        accounts = []

    account_ids = set()

    for account in accounts:
        if not isinstance(account, dict):
            errors.append("账户信息格式错误")
            continue

        account_id = account.get("account_id")

        if not account_id:
            errors.append("账户缺少 account_id")
        elif account_id in account_ids:
            errors.append(f"账户 ID 重复：{account_id}")
        else:
            account_ids.add(account_id)

        # 检查账户余额
        for field in ("initial_balance", "balance"):
            if field in account:
                value = account[field]

                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                ):
                    errors.append(f"账户 {account_id} 的 {field} 不是有效数字")
                elif value < 0:
                    errors.append(f"账户 {account_id} 的 {field} 不能为负数")

    # 5. 检查交易列表
    transactions = scenario["transactions"]

    if not isinstance(transactions, list) or not transactions:
        errors.append("transactions 必须是非空列表")
        transactions = []

    transaction_ids = set()
    has_income = False
    has_expense = False

    for transaction in transactions:
        if not isinstance(transaction, dict):
            errors.append("交易记录格式错误")
            continue

        transaction_id = transaction.get("transaction_id")

        if not transaction_id:
            errors.append("交易缺少 transaction_id")
        elif transaction_id in transaction_ids:
            errors.append(f"交易 ID 重复：{transaction_id}")
        else:
            transaction_ids.add(transaction_id)

        # 检查交易金额
        amount = transaction.get("amount")

        if (
            not isinstance(amount, (int, float))
            or isinstance(amount, bool)
        ):
            errors.append(f"交易 {transaction_id} 的金额不是有效数字")
        elif amount < 0:
            errors.append(f"交易 {transaction_id} 的金额不能为负数")

        # 检查交易引用的账户
        account_id = transaction.get("account_id")

        if account_id not in account_ids:
            errors.append(
                f"交易 {transaction_id} 引用了不存在的账户：{account_id}"
            )

        # 统计收入和支出
        transaction_type = transaction.get("transaction_type")

        if transaction_type in {"income", "transfer_in", "refund"}:
            has_income = True
        elif transaction_type in {"expense", "transfer_out"}:
            has_expense = True
        else:
            errors.append(
                f"交易 {transaction_id} 的 transaction_type 不正确"
            )

    # 6. 检查普通银行场景是否同时包含收入和支出
    if scenario.get("scenario_type") == "A":
        if not has_income:
            errors.append("普通用户场景缺少收入交易")

        if not has_expense:
            errors.append("普通用户场景缺少支出交易")

    return len(errors) == 0, errors
