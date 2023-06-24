# Ichigen Coder: A Cluster of Coding Bots

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)


## Introduction
Ichigen Coder is an assembly of AI bots, driven by Large Language Model technology, designed to augment the capabilities of human developers, simplifying the coding process and boosting efficiency in software development, so that human developers (including the repo owner) can slack off while working :smile:. It's still at very inital stage and currently focuses on `codebase analyzer`.

## Codebase Analyzer
This module is to help a human developer quickly understand a large codebase by asking questions to a chatbot.

The main chatbot will ask its chatbot buddies to collect necessary info using various tools in order to give a accurate and in-depth answer. They might interact for several time before the main chatbot gives the final answer.

Sample questions:
```
q1 = "Which url does the ChatBot send request to after a user ask question to it?"
q2 = "How is the authentication done in the ChatBot?"
q3 = "What is the purpose of the ChatBot?"
q4 = "What is parent id?"
q5 = "What is conversation_id?"
q6 = "How can I see if I will use proxy or not?"
q7 = "How can I use this chatbot?"
q8 = "Why the chat generatd by this bot doesn't have title?"
q9 = "Can I download the chat history?"
q10 = "What will happen if user input `!continue`?"
q11 = "What is the main functionality of this file?" # Hard to answer
q12 = "What is the main function of this file?"
q13 = "What is the main functionality of this file?" # NG for 1st time
q14 = "Can you descibe how human can interact with this Chatbot in deatil?"
q15 = "Can you describe what will be executed after the user run this file?"
q16 = "List the names in order of functions that will be called after a user start the bot and send a message to it." # Hard, only focus on details obtain from a certain function, not the whole file. Mainly because the main tool is to focus on the function level, not the file level.
```
