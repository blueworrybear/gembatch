![PyPI - Python Version](https://img.shields.io/pypi/pyversions/gembatch)
[![PyPi](https://img.shields.io/badge/gembatch-v0.1.5-blue?logo=python)](https://pypi.org/project/gembatch/)
![License - MIT](https://img.shields.io/github/license/blueworrybear/gembatch.svg)
![Firebase](https://img.shields.io/badge/Fireabse-orange?logo=firebase)


# gembatch

A Python library simplifies building language chain applications with Gemini, leveraging batch mode for cost-effective prompt processing.

## Introduction

Prompt chaining is a powerful technique for tackling complex tasks by linking multiple prompts together. Numerous libraries like Langchain offer convenient features for building applications with this approach. However, one crucial aspect often overlooked is cost efficiency.
Many AI service providers offer batch processing modes with significant discounts (often around 50%) in exchange for longer turnaround times. While enticing, leveraging these batch discounts within a prompt chaining workflow can be challenging. Instead of executing API calls sequentially, developers must manage intricate processes:

- Batching requests: Accumulating prompts into batches.
- Asynchronous handling: Polling and waiting for batch job completion.
- Result processing: Extracting and mapping results to the correct chain segment.

This complexity is compounded by considerations like rate limits, error handling, and potential retries. Implementing such a system often leads to convoluted code, hindering readability and maintainability.
This is where GemBatch shines. GemBatch is a framework designed to seamlessly integrate batch processing into prompt chaining workflows without sacrificing simplicity. It allows developers to define their prompt chains sequentially, just as they would with traditional approaches, while automatically optimizing execution using batch APIs behind the scenes. This abstraction simplifies development, improves code clarity, and unlocks significant cost savings.

## Example at a Glance

This example demonstrates how to create a prompt chain using `gembatch.submit()` within your Firebase environment.

```py
import gembath


# Task A
def task_a_prompt1():
   gembatch.submit(
       {
           "contents": [
               {
                   "role": "user",
                   "parts": [{"text": "some prompts..."}],
               }
           ],
       }, # prompt 1
       "publishers/google/models/gemini-1.5-pro-002",
       task_a_prompt2
   )


def task_a_prompt2(response: generative_models.GenerationResponse):
   gembatch.submit(
       {
           "contents": [
               {
                   "role": "model",
                   "parts": [{"text": response.text}],
               },
               {
                   "role": "user",
                   "parts": [{"text": "some prompts..."}],
               }
           ],
       }, # prompt 2
       "publishers/google/models/gemini-1.5-pro-002",
       task_a_output
   )


def task_a_output(response: generative_models.GenerationResponse):
   print(response.text)

```

The code defines three functions: `task_a_prompt1`, `task_a_prompt2`, and `task_a_output`. These functions represent the steps in your prompt chain.

1. `task_a_prompt1():`

    - This function initiates the prompt chain.
    - It uses gembatch.submit() to send the first prompt to Gemini.
    - The prompt is defined as a dictionary, following the structure of [GenerateContentRequest](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference#request_body)
    - It specifies the Gemini model to use ("publishers/google/models/gemini-1.5-pro-002").
    - It designates task_a_prompt2 as the callback function to be executed when the response for this prompt is received.

2. task_a_prompt2(response):

    - This function is the callback function for the first prompt. It receives the response from Gemini as an argument.
    - It constructs the second prompt, including the model's response from the previous step and a new user message.
    - It again uses gembatch.submit() to send this prompt to Gemini.
    - It specifies the same Gemini model.
    - It sets task_a_output as the callback function for the second prompt.

3. `task_a_output(response):`

    - This function is the callback function for the second prompt.
    - It receives the final response from Gemini.
    - It simply prints the response text.

The chain is started by calling the first function:

```
task_a_prompt1()
```

This pattern of chaining prompts and callbacks allows you to create complex interactions with the language model, where each step depends on the output of the previous step. The gembatch library handles the underlying communication with Gemini and manages the execution of the prompt chain using efficient batch jobs. This not only simplifies development but also reduces costs by taking advantage of Gemini's batch pricing, which offers a 50% discount compared to individual requests.


## How Gembatch Works

![](./docs/gembatch_steps.gif)

This flowchart illustrates how Gembatch efficiently manages multiple prompt chains concurrently using batch processing. Here's a breakdown:

1. Independent Prompt Chains:

    The diagram depicts three separate prompt chains (Task A, Task B, Task C), each with its own sequence of prompts and responses.
    Each chain represents a distinct conversation or task with the language model.

2. Gembatch Submission:

    As each prompt in a chain is ready for submission, Gembatch's submit() function is called.
    Instead of sending the prompt to Gemini immediately, Gembatch adds it to a job queue.

3. Batch Formation:

    Gembatch intelligently groups prompts from different chains into batches.
    This is shown in the "Job Queue" where "Batch 1" contains "Prompt 1" from each of the tasks.

4. Batch Execution:

    Gembatch periodically sends these batches to Gemini for processing.
    This minimizes the number of interactions with the API and leverages Gemini's batch discounts.

5. Response Handling:

    When Gemini returns responses for a batch, Gembatch routes them back to the appropriate prompt chains.
    For instance, "Responses Batch 1" is distributed back to each task, triggering the next step in their respective chains.

6. Chain Continuation:

    Each task processes the response and, if necessary, generates the next prompt in its sequence.
    This continues until the chain reaches its "Output" stage, signifying the completion of that specific task.

**Key Takeaways:**

1. Efficiency: Gembatch optimizes prompt processing by grouping them into batches, reducing API calls and costs.
2. Concurrency: Multiple prompt chains can progress simultaneously, improving overall throughput.
3. Simplified Management: Gembatch handles the complexities of batching and response routing, allowing you to focus on designing your prompt chains.

## Ready to get started?

Now that you have an overview of Gembatch, learn how to install and configure it in your Firebase project with our step-by-step [Installation Guide](./docs/installation.md).
