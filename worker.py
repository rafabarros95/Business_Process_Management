import asyncio  # import asyncio for asynchronous programming
from pyzeebe import ZeebeWorker, Job, JobController, create_insecure_channel  # import necessary classes from pyzeebe


async def on_error(exception: Exception, job: Job, job_controller: JobController):  # define an error handler for job exceptions
    print(f"Job failed: {exception}")
    await job_controller.set_error_status(job, str(exception))


async def main():
    channel = create_insecure_channel(grpc_address="localhost:26500")
    worker = ZeebeWorker(channel)

    @worker.task(task_type="score-applicant", exception_handler=on_error)
    async def score_applicant(applicant_name: str, credit_score: int, loan_amount: int) -> dict:
        approved = credit_score >= 700 and loan_amount <= 10000
        result = "APPROVED" if approved else "REJECTED"
        print(f"Processing {applicant_name}: credit={credit_score}, amount={loan_amount} -> {result}")
        return {
            "approved": approved,
            "decision_reason": "Within limits" if approved else "Does not meet criteria"
        }

    print("Worker running... (Ctrl+C to stop)")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
