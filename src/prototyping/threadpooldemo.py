import concurrent.futures
import time
import random


# Define the worker function:
def worker(task_num):
    duration = 5  # random.randint(1, 5)  # Random duration between 1 to 5 seconds
    print(f"Task {task_num} starts, will run for {duration} seconds...")
    time.sleep(duration)
    print(f"Task {task_num} finished after {duration} seconds!")
    return f"Task {task_num} result"


# Main execution:
if __name__ == "__main__":
    NUM_TASKS = 10  # Number of tasks to run
    MAX_WORKERS = 3  # Maximum number of concurrent tasks

    # Using ThreadPoolExecutor ###THIS BLOCKS###:
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit tasks to executor:
        futures = [executor.submit(worker, i) for i in range(NUM_TASKS)]

        # Collect results:
        for future in concurrent.futures.as_completed(futures):
            print(future.result())

    print("All tasks completed!")
