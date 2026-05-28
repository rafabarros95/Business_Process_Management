import asyncio  # import asyncio for asynchronous programming
from pyzeebe import ZeebeWorker, Job, JobController, create_insecure_channel  # import necessary classes from pyzeebe


async def on_error(exception: Exception, job: Job, job_controller: JobController):  # define an error handler for job exceptions
    print(f"Job failed: {exception}")
    await job_controller.set_error_status(job, str(exception))


async def main():
    channel = create_insecure_channel(grpc_address="localhost:26500") # create a gRPC channel to connect to the Zeebe broker / "Insecure" just means no SSL — fine for local dev
    worker = ZeebeWorker(channel)  # create a Zeebe worker using the channel

    @worker.task(task_type="score-applicant", exception_handler=on_error)  # register a task handler for the "score-applicant" task type, with the error handler - check the task type in the BPMN model
    async def score_applicant(applicant_name: str, credit_score: int, loan_amount: int) -> dict:
        approved = credit_score >= 700 and loan_amount <= 10000
        result = "APPROVED" if approved else "REJECTED"
        print(f"Processing {applicant_name}: credit={credit_score}, amount={loan_amount} -> {result}")
        return {
            "approved": approved,
            "decision_reason": "Within limits" if approved else "Does not meet criteria"
        }

    print("Worker running...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
