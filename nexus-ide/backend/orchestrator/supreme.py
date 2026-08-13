"""SupremeOrchestrator — top-level orchestrator coordinating multi-agent execution.

Receives business goals, decomposes into stories, allocates agents,
and tracks execution via WorkflowTracker and EventBus.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.agents.base import AgentBase, AgentRequest
from backend.observability.event_bus import EventBus
from backend.observability.events import Event
from backend.observability.workflow_tracker import WorkflowTracker
from backend.orchestrator.agent_pool import AgentPool
from backend.orchestrator.allocator import AgentAllocator
from backend.orchestrator.decomposer import GoalDecomposer, StoryPriority, UserStory
from backend.tools.ollama_client import OllamaClient
from backend.agents.reflection_system import ReflectionSystem, ReflectionType
from backend.knowledge.memory import MemoryStore
from datetime import datetime

logger = logging.getLogger(__name__)


# Map story types to agent capabilities
STORY_TO_CAPABILITY: dict[str, str] = {
    "architect": "design",
    "coder": "code_generation",
    "tester": "test_repair",
    "reviewer": "code_review",
    "documenter": "documentation",
    "optimizer": "optimization",
    "debugger": "debugging",
    "researcher": "research",
}


class SupremeOrchestrator:
    """Top-level orchestrator for the NEXUS autonomous pipeline."""

    def __init__(
        self,
        registry: dict[str, AgentBase],
        decomposer: GoalDecomposer | None = None,
        allocator: AgentAllocator | None = None,
        event_bus: EventBus | None = None,
        workflow_tracker: WorkflowTracker | None = None,
        agent_pool: AgentPool | None = None,
        ollama_client: OllamaClient | None = None,
        agent_timeout: float = 300.0,
        memory_system: MemoryStore | None = None,
        enable_reflection: bool = True,
    ) -> None:
        self._registry = registry
        self._decomposer = decomposer or GoalDecomposer()
        self._allocator = allocator or AgentAllocator(registry)
        self._bus = event_bus or EventBus()
        self._tracker = workflow_tracker or WorkflowTracker()
        self._pool = agent_pool or AgentPool()
        self._ollama_client = ollama_client
        self._agent_timeout = agent_timeout
        self._running = False
        
        # Initialize reflection system
        self._memory_system = memory_system or MemoryStore()
        self._enable_reflection = enable_reflection
        if enable_reflection:
            self._reflection_system = ReflectionSystem(self._memory_system, self._bus)
        else:
            self._reflection_system = None

    async def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish an event to the event bus."""
        event = Event(type=event_type, payload=payload)
        await self._bus.publish(event)

    async def orchestrate(
        self,
        goal: str,
        context: str = "",
        stack: str = "fastapi",
    ) -> dict[str, Any]:
        """Execute the full pipeline from goal to software.

        Args:
            goal: Business objective.
            context: Additional project context.
            stack: Target technology stack.

        Returns:
            Execution summary with workflow_id, steps, and status.
        """
        self._running = True

        # 1. Decompose goal into stories
        await self._publish_event("orchestrator.started", {"goal": goal})
        stories = await self._decomposer.decompose(goal, context)
        logger.info("Decomposed goal into %d stories", len(stories))

        # 2. Create workflow
        workflow = self._tracker.create_workflow(
            story_id="supreme",
            goal=goal,
            metadata={"stack": stack, "story_count": len(stories)},
        )
        self._tracker.start_workflow(workflow.workflow_id)

        # 3. Execute stories in priority order
        priority_weights = {
            StoryPriority.CRITICAL: 4,
            StoryPriority.HIGH: 3,
            StoryPriority.MEDIUM: 2,
            StoryPriority.LOW: 1,
        }
        stories.sort(key=lambda s: priority_weights.get(s.priority, 0), reverse=True)
        results: list[dict[str, Any]] = []

        for story in stories:
            if not self._running:
                break

            result = await self._execute_story(
                workflow.workflow_id, story, stack,
            )
            results.append(result)

        # 4. Complete workflow
        failed = any(r.get("status") == "failed" for r in results)
        final_status = "failed" if failed else "completed"
        self._tracker.complete_workflow(workflow.workflow_id, final_status)

        # 5. Perform reflection on the entire orchestration process
        if self._enable_reflection and self._reflection_system:
            await self._reflect_on_orchestration(workflow.workflow_id, goal, results, final_status)

        await self._publish_event("orchestrator.completed", {
            "workflow_id": workflow.workflow_id,
            "status": final_status,
            "stories": len(stories),
        })

        return {
            "workflow_id": workflow.workflow_id,
            "status": final_status,
            "stories_executed": len(results),
            "results": results,
        }

    async def _execute_story(
        self,
        workflow_id: str,
        story: UserStory,
        stack: str,
    ) -> dict[str, Any]:
        """Execute a single user story with real agent execution."""
        step = self._tracker.add_step(
            workflow_id,
            name=story.title,
            agent=story.assigned_agent,
            inputs={"description": story.description, "criteria": story.acceptance_criteria},
        )

        await self._publish_event("story.started", {
            "story_id": story.story_id,
            "title": story.title,
            "agent": story.assigned_agent,
        })

        # Determine capability from assigned agent
        capability = STORY_TO_CAPABILITY.get(
            story.assigned_agent,
            "code_generation",
        )

        # Allocate agent with fallback chain
        agent = await self._allocate_with_fallback(capability, stack, story.assigned_agent)
        if not agent:
            self._tracker.fail_step(workflow_id, step.step_id, "No agent available after fallback")
            return {"story_id": story.story_id, "status": "failed", "error": "No agent available"}

        try:
            # Execute agent with resource management
            result = await self._execute_agent(agent, story, stack, workflow_id, step)
            
            if result["status"] == "completed":
                self._tracker.complete_step(workflow_id, step.step_id, outputs=result.get("outputs", {}))
                await self._publish_event("story.completed", {"story_id": story.story_id})
            else:
                self._tracker.fail_step(workflow_id, step.step_id, result.get("error", "Unknown error"))
                await self._publish_event("story.failed", {"story_id": story.story_id, "error": result.get("error")})
            
            return result

        except Exception as exc:
            self._tracker.fail_step(workflow_id, step.step_id, str(exc))
            await self._publish_event("story.failed", {"story_id": story.story_id, "error": str(exc)})
            return {"story_id": story.story_id, "status": "failed", "error": str(exc)}

    async def _reflect_on_orchestration(self, workflow_id: str, goal: str, 
                                      results: list[dict[str, Any]], final_status: str) -> None:
        """Reflect on the orchestration process and generate insights."""
        if not self._reflection_system:
            return
        
        # Prepare orchestration data for reflection
        orchestration_data = {
            "process_id": f"orchestration_{workflow_id}",
            "goal": goal,
            "final_status": final_status,
            "stories_executed": len(results),
            "successful_stories": len([r for r in results if r.get("status") == "completed"]),
            "failed_stories": len([r for r in results if r.get("status") == "failed"]),
            "workflow_id": workflow_id,
            "timestamp": datetime.now().isoformat(),
            "performance_metrics": {
                "success_rate": len([r for r in results if r.get("status") == "completed"]) / len(results) if results else 0.0,
                "efficiency": self._calculate_orchestration_efficiency(results),
                "quality": self._calculate_orchestration_quality(results),
            },
            "decisions": [
                {
                    "type": "story_execution",
                    "story_id": r.get("story_id"),
                    "agent": r.get("agent"),
                    "success": r.get("status") == "completed",
                    "confidence": 0.8  # Default confidence
                }
                for r in results
            ],
            "outcomes": [
                {
                    "success_score": 1.0 if r.get("status") == "completed" else 0.0,
                    "efficiency_score": 0.8,  # Default efficiency
                    "quality_score": 0.9,  # Default quality
                    "story_id": r.get("story_id")
                }
                for r in results
            ],
            "context": {
                "complexity": "medium",
                "time_pressure": "normal",
                "resources": "sufficient",
                "domain": "software_development",
                "collaboration": "multi_agent"
            }
        }
        
        try:
            # Perform reflection
            reflection_result = await self._reflection_system.reflect_on_task(
                agent_id="supreme_orchestrator",
                task_result=orchestration_data,
                reflection_types=[ReflectionType.PERFORMANCE, ReflectionType.STRATEGY, ReflectionType.LEARNING]
            )
            
            # Log reflection insights
            logger.info(f"Orchestration reflection completed for workflow {workflow_id}")
            logger.info(f"Confidence score: {reflection_result.confidence_score}")
            logger.info(f"Improvement suggestions: {len(reflection_result.improvement_suggestions)}")
            
            # Store reflection for future reference
            await self._store_reflection_insights(workflow_id, reflection_result)
            
            # Emit reflection event.
            #
            # This used to call ``self._bus.emit(...)``. ``EventBus`` has no
            # ``emit`` — only ``publish`` — so every reflection raised
            # AttributeError straight into the broad ``except`` below and was
            # logged as "Failed to perform orchestration reflection". The
            # reflection itself had already succeeded; only its announcement
            # was lost, and the log made it look like the whole step failed.
            # The keyword is ``payload``, matching ``_publish_event`` above.
            await self._publish_event(
                "orchestration_reflection_completed",
                {
                    "workflow_id": workflow_id,
                    "confidence_score": reflection_result.confidence_score,
                    "improvements_count": len(reflection_result.improvement_suggestions),
                    "final_status": final_status,
                },
            )
            
        except Exception as e:
            logger.error(f"Failed to perform orchestration reflection: {e}")
    
    def _calculate_orchestration_efficiency(self, results: list[dict[str, Any]]) -> float:
        """Calculate efficiency of the orchestration process."""
        if not results:
            return 0.0
        
        # Base efficiency on success rate and execution time
        success_rate = len([r for r in results if r.get("status") == "completed"]) / len(results)
        
        # Assume good efficiency if most stories succeed
        return success_rate * 0.9  # Slightly lower than perfect efficiency
    
    def _calculate_orchestration_quality(self, results: list[dict[str, Any]]) -> float:
        """Calculate quality of the orchestration process."""
        if not results:
            return 0.0
        
        # Quality based on success rate and error handling
        success_rate = len([r for r in results if r.get("status") == "completed"]) / len(results)
        
        # Quality is slightly higher than efficiency as we consider error handling
        return min(1.0, success_rate * 1.1)
    
    async def _store_reflection_insights(self, workflow_id: str, 
                                       reflection_result) -> None:
        """Store reflection insights for future reference."""
        # Store in memory system for future learning
        await self._memory_system.store(
            key=f"orchestration_reflection_{workflow_id}",
            value={
                "workflow_id": workflow_id,
                "timestamp": reflection_result.timestamp.isoformat(),
                "confidence_score": reflection_result.confidence_score,
                "improvement_suggestions": reflection_result.improvement_suggestions,
                "learning_insights": reflection_result.learning_insights,
                "action_items": reflection_result.action_items,
                "self_critique": reflection_result.self_critique
            },
            category="orchestration_reflection"
        )
    
    async def get_reflection_summary(self, workflow_id: str) -> dict[str, Any]:
        """Get reflection summary for a specific workflow."""
        if not self._reflection_system:
            return {"error": "Reflection system not enabled"}
        
        try:
            # Retrieve from memory system
            reflection_data = await self._memory_system.retrieve(
                key=f"orchestration_reflection_{workflow_id}",
                category="orchestration_reflection"
            )
            
            if not reflection_data:
                return {"error": "No reflection found for workflow"}
            
            return {
                "workflow_id": workflow_id,
                "reflection_summary": reflection_data
            }
            
        except Exception as e:
            logger.error(f"Failed to retrieve reflection summary: {e}")
            return {"error": str(e)}
    
    async def get_system_reflection_stats(self) -> dict[str, Any]:
        """Get system-wide reflection statistics."""
        if not self._reflection_system:
            return {"error": "Reflection system not enabled"}
        
        try:
            return await self._reflection_system.get_system_reflection_stats()
        except Exception as e:
            logger.error(f"Failed to get system reflection stats: {e}")
            return {"error": str(e)}

    async def _allocate_with_fallback(
        self,
        capability: str,
        stack: str,
        preferred_agent: str,
    ) -> AgentBase | None:
        """Allocate agent with fallback chain for graceful degradation."""
        # Try preferred agent first
        if preferred_agent in self._registry:
            try:
                await asyncio.wait_for(
                    self._pool.acquire(preferred_agent),
                    timeout=5.0,
                )
                return self._registry[preferred_agent]
            except asyncio.TimeoutError:
                logger.warning("Preferred agent %s busy, trying fallback", preferred_agent)
            except Exception as exc:
                logger.warning("Failed to acquire %s: %s", preferred_agent, exc)

        # Try fallback chain from allocator
        fallback_chain = self._allocator.get_fallback_chain(capability)
        for agent_name in fallback_chain:
            if agent_name in self._registry and agent_name != preferred_agent:
                try:
                    await asyncio.wait_for(
                        self._pool.acquire(agent_name),
                        timeout=5.0,
                    )
                    logger.info("Using fallback agent %s for %s", agent_name, capability)
                    return self._registry[agent_name]
                except asyncio.TimeoutError:
                    logger.warning("Fallback agent %s busy, trying next", agent_name)
                except Exception as exc:
                    logger.warning("Failed to acquire fallback %s: %s", agent_name, exc)

        # Last resort: try any available agent
        for agent_name, agent in self._registry.items():
            try:
                await asyncio.wait_for(
       
                    self._pool.acquire(agent_name),
                    timeout=2.0,
                )
                logger.warning("Using last resort agent %s for %s", agent_name, capability)
                return agent
            except (asyncio.TimeoutError, Exception):
                continue

        return None

    async def _execute_agent(
        self,
        agent: AgentBase,
        story: UserStory,
        stack: str,
        workflow_id: str,
        step: Any,
    ) -> dict[str, Any]:
        """Execute agent with real agent.run() and workflow tracking."""
        agent_name = agent.name
        
        logger.info("Starting agent execution: %s for story %s", agent_name, story.story_id)
        
        # Create Ollama client if not provided
        if self._ollama_client is None:
            from backend.config.settings import get_settings
            settings = get_settings()
            self._ollama_client = OllamaClient(base_url=settings.ollama_host)

        # Build the query for the agent
        query = f"""Task: {story.title}
Description: {story.description}
Acceptance Criteria: {story.acceptance_criteria}
Technology Stack: {stack}

Please complete this task following the acceptance criteria."""

        # Create agent request
        request = AgentRequest(
            session_id=workflow_id,
            query=query,
            client=self._ollama_client,
            context={"stack": stack, "story_id": story.story_id},
            max_iterations=7,
            enable_thinking=False,
        )

        # Execute agent with streaming and timeout
        output_parts = []
        try:
            # Wrap the entire execution in a timeout
            await asyncio.wait_for(
                self._collect_agent_output(agent, request, output_parts, agent_name, story, step),
                timeout=self._agent_timeout
            )

            full_output = "".join(output_parts)
            logger.info("Agent %s completed successfully for story %s", agent_name, story.story_id)
            
            return {
                "story_id": story.story_id,
                "status": "completed",
                "outputs": {"result": full_output},
                "agent": agent_name,
            }

        except asyncio.TimeoutError:
            logger.error("Agent %s execution timed out after %s seconds for story %s", 
                        agent_name, self._agent_timeout, story.story_id)
            return {
                "story_id": story.story_id,
                "status": "failed",
                "error": f"Agent execution timed out after {self._agent_timeout} seconds",
                "agent": agent_name,
            }

        except Exception as exc:
            logger.error("Agent %s execution failed: %s", agent_name, exc, exc_info=True)
            return {
                "story_id": story.story_id,
                "status": "failed",
                "error": str(exc),
                "agent": agent_name,
            }

        finally:
            # Release agent resource
            await self._pool.release(agent_name)
            logger.debug("Released agent resource: %s", agent_name)

    async def _collect_agent_output(
        self,
        agent: AgentBase,
        request: AgentRequest,
        output_parts: list[str],
        agent_name: str,
        story: UserStory,
        step: Any,
    ) -> None:
        """Collect agent output from streaming into the output_parts list."""
        async for chunk in agent.run(request):
            output_parts.append(chunk)
            
            # Update workflow with progress
            if len(output_parts) % 100 == 0:
                await self._publish_event("agent.progress", {
                    "agent": agent_name,
                    "story_id": story.story_id,
                    "step_id": step.step_id,
                    "progress": len(output_parts),
                })

    async def stop(self) -> None:
        """Stop orchestration."""
        self._running = False
        logger.info("SupremeOrchestrator stopped")
