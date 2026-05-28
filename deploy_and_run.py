import asyncio
from pyzeebe import ZeebeClient, create_insecure_channel


async def main():
    channel = create_insecure_channel(grpc_address="localhost:26500")
    client = ZeebeClient(channel)

    result = await client.deploy_resource("loan-application.bpmn")
    print(f"Deployed: {result}")

    instance_key = await client.run_process(
        bpmn_process_id="loan-application",
        variables={
            "applicant_name": "Julia Smith",
            "loan_amount": 11000,
            "credit_score": 900,
        }
    )
    print(f"Process instance started: {instance_key}")

    await channel.close()


if __name__ == "__main__":
    asyncio.run(main())
