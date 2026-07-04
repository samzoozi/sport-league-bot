import os
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

LAMBDA_BUILD_DIR = Path(__file__).resolve().parent.parent / "lambda_build"


class BotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.Table(
            self,
            "Table",
            table_name="hangar-sport-bot",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        environment = {
            "BOT_TOKEN": os.environ["BOT_TOKEN"],
            "WEBHOOK_SECRET_TOKEN": os.environ["WEBHOOK_SECRET_TOKEN"],
            "TABLE_NAME": table.table_name,
        }
        # Optional: comma-separated chat IDs the bot is allowed to operate in,
        # set via .env like BOT_TOKEN/WEBHOOK_SECRET_TOKEN above. Chat IDs
        # aren't secret, but they identify which real groups use this
        # deployment, so we keep them out of the committed cdk.json anyway.
        # Left unset by default, same as MIN_PLAYERS/etc. — see CLAUDE.md.
        if allowed_chat_ids := os.environ.get("ALLOWED_CHAT_IDS"):
            environment["ALLOWED_CHAT_IDS"] = allowed_chat_ids

        fn = lambda_.Function(
            self,
            "BotFunction",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambda_function.handler",
            code=lambda_.Code.from_asset(str(LAMBDA_BUILD_DIR)),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=environment,
        )

        table.grant_read_write_data(fn)
        # grant_read_write_data() doesn't include transaction actions, but
        # db.add_transaction (used by /finalize, /charge, /credit, /paid,
        # /chargeall, /creditall) depends on TransactWriteItems.
        table.grant(fn, "dynamodb:TransactWriteItems", "dynamodb:TransactGetItems")

        function_url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        CfnOutput(self, "FunctionUrl", value=function_url.url)
        CfnOutput(self, "TableName", value=table.table_name)
