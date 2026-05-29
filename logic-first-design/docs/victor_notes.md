

Notes on the current version of docs (commit 111dda9a7eedb44d6cbe63d12df92c25b5f3d798)
methodology doc:

For the current stack, it is worth noting that some aspects of what an agent will receive to do a task is not noted here. The python tools contain docstrings that are sent to the agent as part of the tool definitions. Those could contain elements not mentioned in the policy. Not really an issue for our implementation, just something to be aware of, tool documentation (signature etc) can be seen as part of the specifications of a domain.

One thing we have not fully considered is the possibility of contraditions within the policy -> this is when a good agent should raise issue with the agent developer. As we move towards a more holistic understanding of the stakeholders involved in an agent's interactions (the developer on one end and the user on the other), and the question of maintenance, we should think about how our formalism could be used to properly inject issues to be resolved. (can an agent detect that there is ambiguity and hold of, etc)

In the mention of natural language, it is also important to distinguish the policy as a set of rules, the policy as a human written documents used in an organizations, and the system prompt used as input to an llm. We don't want to conflict all of this

About uniqueness: I wonder how important it really is. If we know what the solutions are, we have verifiability. Uniqueness could be treated as a just a degenerate case in which enough constraints are added to limit to a single valid solutions.

Idea: is there a way to construct tasks iteratively by having a system that can suggest constraints iteratively until we get to a final set?
And following on this, I would like to think about whether or not we could dynamically generate tasks such that as we test the LLM the next task is generated based on where the weaknesses are found (e.g. it tends to fail on that constraint etc). Creating tasks is expensive but if we can create them on the fly it allows for something along the line of what the "fluid benchmarking" paper proposed. Could we quickly detect weaknesses?
So instead of treating the policy / tasks as fixed, we would dynamically update it to probe the model?


Questions: what types of reasoning or logic is not really incorporated here? where could we push the boundary? 

Questions: It seems that people have already tried to use logic solver integrated with LLM to improve solving capacities. Could we use that as part of the user simulator?

Questions: Could we encode the dialogue logic as well? Some logic on dialogue acts etc to detect issues, errors, or guide the user simulator?

Questions: One problem we often have is benchmark maxing. One idea I had was that if the world is defined logically, we might be able to more easily build a counterfactual one and test whether or not llm had been overfitted on a particular benchmark? We could test that with taubench? Same difficulty etc but counterfactual?

Questions: we are using ASP but are there other logical systems can could be used? what would we gain? 

Questions: Telecom is different type of domains, it is implemented as a code much more than airline (basically a "simulated phone" go look at the code). How could we formalize this? Is it possible?


Carrying out conversations is costly. I think for all the tasks we should be able to test them by giving them as direct task to the agent in a format that it can solves on its own (without needing the user - we aready have a "solo" mode in the code but it is only for telecom). It would help directly understand the difficulty of the task outside of the difficulty added by the need to interact with the user.


For intent_noop: one thing that we are missing in tau-bench is the fact that some read actions are also necessary to solve a taks (for example authentication). We should be able to make sure the agent has indeed carried out those required actions.


I think multi-turn world dynamics is something we should try and include at some point. I think TIME is a big under-studied aspect in benchmarking.