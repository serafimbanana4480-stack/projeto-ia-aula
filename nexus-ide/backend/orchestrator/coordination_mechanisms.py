"""Distributed Agent Coordination Mechanisms.

Implements consensus, conflict resolution, distributed locking, leader election,
coordination channels, task leases, synchronization barriers, and distributed semaphores.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class ConsensusState(str, Enum):
    """Raft-like consensus states."""
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class LockType(str, Enum):
    """Types of distributed locks."""
    TASK = "task"
    RESOURCE = "resource"
    WORKSPACE = "workspace"
    SESSION = "session"


@dataclass
class ConsensusNode:
    """Node in consensus algorithm."""
    node_id: str
    term: int = 0
    state: ConsensusState = ConsensusState.FOLLOWER
    voted_for: str | None = None
    votes_received: set[str] = field(default_factory=set)
    last_heartbeat: float = field(default_factory=time.time)
    leader_id: str | None = None
    
    def is_leader(self) -> bool:
        return self.state == ConsensusState.LEADER
        
    def is_candidate(self) -> bool:
        return self.state == ConsensusState.CANDIDATE


@dataclass
class DistributedLock:
    """Distributed lock with timeout and renewal."""
    lock_id: str
    resource_id: str
    owner_id: str
    acquired_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 30.0)
    auto_renew: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
        
    def time_to_expiry(self) -> float:
        return max(0, self.expires_at - time.time())


@dataclass
class TaskLease:
    """Task lease for distributed task ownership."""
    lease_id: str
    task_id: str
    owner_id: str
    acquired_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 60.0)
    heartbeat_interval: float = 10.0
    last_heartbeat: float = field(default_factory=time.time)
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
        
    def needs_heartbeat(self) -> bool:
        return time.time() - self.last_heartbeat > self.heartbeat_interval


class ConsensusManager:
    """Raft-like consensus implementation for leader election."""
    
    def __init__(
        self,
        node_id: str,
        redis_url: str = "redis://localhost:6379",
        election_timeout: float = 10.0,
        heartbeat_interval: float = 2.0,
        cluster_size: int = 3,
    ):
        self.node_id = node_id
        self.redis_url = redis_url
        self.election_timeout = election_timeout
        self.heartbeat_interval = heartbeat_interval
        self.cluster_size = cluster_size
        
        self._redis: redis.Redis | None = None
        self._node: ConsensusNode = ConsensusNode(node_id=node_id)
        self._election_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        
    def _has_majority(self, vote_count: int) -> bool:
        """Check if vote count constitutes a majority.
        
        Majority requires more than half of the cluster:
        - 3 nodes: need 2+ votes
        - 5 nodes: need 3+ votes
        """
        return vote_count > self.cluster_size // 2
        
    async def start(self) -> None:
        """Start consensus manager."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        
        # Start background tasks
        self._election_task = asyncio.create_task(self._election_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        logger.info("Started consensus manager for node %s", self.node_id)
        
    async def stop(self) -> None:
        """Stop consensus manager."""
        if self._election_task:
            self._election_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            
        if self._redis:
            await self._redis.close()
            
        logger.info("Stopped consensus manager for node %s", self.node_id)
        
    async def _election_loop(self) -> None:
        """Main election loop."""
        while True:
            try:
                await asyncio.sleep(self.election_timeout)
                await self._start_election()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Election loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop for leader and followers."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _start_election(self) -> None:
        """Start election process."""
        self._node.term += 1
        self._node.state = ConsensusState.CANDIDATE
        self._node.voted_for = self.node_id
        self._node.votes_received = {self.node_id}
        
        logger.info("Node %s starting election for term %d", self.node_id, self._node.term)
        
        # Vote for self
        await self._cast_vote(self.node_id, self.node_id, self.node.term)
        
        # Request votes from other nodes
        await self._request_votes()
        
        # Wait for election results
        await asyncio.sleep(self.election_timeout)
        
        # Check election results
        if self._has_majority(len(self._node.votes_received)):
            self._node.state = ConsensusState.LEADER
            await self._become_leader()
        else:
            self._node.state = ConsensusState.FOLLOWER
            await self._become_follower()
            
    async def _cast_vote(self, candidate_id: str, voter_id: str, term: int) -> None:
        """Cast vote to all nodes."""
        vote_data = {
            "candidate_id": candidate_id,
            "voter_id": voter_id,
            "term": term,
            "timestamp": time.time(),
        }
        
        await self._redis.publish("consensus:votes", json.dumps(vote_data))
        
    async def _request_votes(self) -> None:
        """Request votes from other nodes."""
        request_data = {
            "candidate_id": self.node_id,
            "term": self._node.term,
            "timestamp": time.time(),
        }
        
        await self._redis.publish("consensus:election", json.dumps(request_data))
        
    async def _become_leader(self) -> None:
        """Become leader and start leader duties."""
        self._node.leader_id = self.node_id
        logger.info("Node %s became leader for term %d", self.node_id, self._node.term)
        
        # Store leader info
        await self._redis.setex(
            f"consensus:leader:{self.node.term}",
            60,  # 1 minute
            json.dumps({
                "leader_id": self.node_id,
                "term": self.node.term,
                "timestamp": time.time(),
            })
        )
        
    async def _become_follower(self) -> None:
        """Become follower."""
        self._node.leader_id = None
        logger.info("Node %s became follower for term %d", self.node_id, self._node.term)
        
    async def _send_heartbeat(self) -> None:
        """Send heartbeat to maintain leadership."""
        heartbeat_data = {
            "node_id": self.node_id,
            "term": self._node.term,
            "state": self._node.state.value,
            "leader_id": self._node.leader_id,
            "timestamp": time.time(),
        }
        
        await self._redis.publish("consensus:heartbeat", json.dumps(heartbeat_data))
        self._node.last_heartbeat = time.time()
        
    def is_leader(self) -> bool:
        """Check if this node is the current leader."""
        return self._node.is_leader()
        
    def get_leader(self) -> str | None:
        """Get current leader ID."""
        return self._node.leader_id


class DistributedLockManager:
    """Distributed lock manager with Redis backend."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._lock_renewal_tasks: dict[str, asyncio.Task] = {}
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        logger.info("Connected to DistributedLockManager")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        for task in self._lock_renewal_tasks.values():
            task.cancel()
            
        if self._redis:
            await self._redis.close()
            
    async def acquire_lock(
        self,
        resource_id: str,
        owner_id: str,
        lock_type: LockType = LockType.TASK,
        timeout: float = 30.0,
        auto_renew: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> DistributedLock | None:
        """Acquire distributed lock."""
        if not self._redis:
            raise RuntimeError("Lock manager not connected")
            
        lock_id = f"lock:{resource_id}:{uuid.uuid4().hex[:8]}"
        
        # Check if lock already exists
        existing_key = f"locks:{resource_id}"
        existing_data = await self._redis.get(existing_key)
        
        if existing_data:
            existing_lock = json.loads(existing_data)
            if not existing_lock["is_expired"]:
                return None  # Lock already held
                
        # Create new lock
        lock = DistributedLock(
            lock_id=lock_id,
            resource_id=resource_id,
            owner_id=owner_id,
            expires_at=time.time() + timeout,
            auto_renew=auto_renew,
            metadata=metadata or {},
        )
        
        # Store lock
        await self._redis.setex(
            existing_key,
            int(timeout + 10),  # Extra time for renewal
            json.dumps({
                "lock_id": lock_id,
                "resource_id": resource_id,
                "owner_id": owner_id,
                "acquired_at": lock.acquired_at,
                "expires_at": lock.expires_at,
                "auto_renew": lock.auto_renew,
                "metadata": lock.metadata,
                "is_expired": False,
            })
        )
        
        # Start renewal task if needed
        if lock.auto_renew:
            renewal_task = asyncio.create_task(self._renew_lock(lock))
            self._lock_renewal_tasks[lock_id] = renewal_task
            
        logger.debug("Acquired lock %s for resource %s", lock_id, resource_id)
        return lock
        
    async def release_lock(self, lock_id: str) -> bool:
        """Release distributed lock."""
        if not self._redis:
            return False
            
        # Cancel renewal task
        if lock_id in self._lock_renewal_tasks:
            self._lock_renewal_tasks[lock_id].cancel()
            del self._lock_renewal_tasks[lock_id]
            
        # Find and delete lock
        pattern = "locks:*"
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                try:
                    data = await self._redis.get(key)
                    if data:
                        lock_info = json.loads(data)
                        if lock_info["lock_id"] == lock_id:
                            await self._redis.delete(key)
                            logger.debug("Released lock %s", lock_id)
                            return True
                except Exception as exc:
                    logger.error("Error releasing lock %s: %s", key, exc)
                    
        return False
        
    async def _renew_lock(self, lock: DistributedLock) -> None:
        """Renew lock automatically."""
        while True:
            try:
                await asyncio.sleep(lock.time_to_expiry() / 2)  # Renew at half-time
                
                if not lock.auto_renew:
                    break
                    
                # Update expiry
                lock.expires_at = time.time() + 30.0  # Reset to 30 seconds
                
                # Update in Redis
                key = f"locks:{lock.resource_id}"
                existing_data = await self._redis.get(key)
                
                if existing_data:
                    lock_info = json.loads(existing_data)
                    if lock_info["owner_id"] == lock.owner_id:
                        lock_info["expires_at"] = lock.expires_at
                        await self._redis.setex(key, 40, json.dumps(lock_info))
                        logger.debug("Renewed lock %s", lock.lock_id)
                    else:
                        break  # Lock was taken by someone else
                else:
                    break  # Lock no longer exists
                    
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error renewing lock %s: %s", lock.lock_id, exc)
                await asyncio.sleep(1.0)
                
    async def get_lock_info(self, resource_id: str) -> dict[str, Any] | None:
        """Get information about a lock."""
        if not self._redis:
            return None
            
        key = f"locks:{resource_id}"
        data = await self._redis.get(key)
        
        if data:
            return json.loads(data)
        return None


class TaskLeaseManager:
    """Task lease manager for distributed task ownership."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._lease_heartbeat_tasks: dict[str, asyncio.Task] = {}
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        logger.info("Connected to TaskLeaseManager")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        for task in self._lease_heartbeat_tasks.values():
            task.cancel()
            
        if self._redis:
            await self._redis.close()
            
    async def create_lease(
        self,
        task_id: str,
        owner_id: str,
        timeout: float = 60.0,
        heartbeat_interval: float = 10.0,
    ) -> TaskLease:
        """Create task lease."""
        if not self._redis:
            raise RuntimeError("Lease manager not connected")
            
        lease_id = f"lease:{task_id}:{uuid.uuid4().hex[:8]}"
        
        lease = TaskLease(
            lease_id=lease_id,
            task_id=task_id,
            owner_id=owner_id,
            expires_at=time.time() + timeout,
            heartbeat_interval=heartbeat_interval,
        )
        
        # Store lease
        key = f"leases:{task_id}"
        await self._redis.setex(
            key,
            int(timeout + 10),  # Extra time for heartbeat
            json.dumps({
                "lease_id": lease_id,
                "task_id": task_id,
                "owner_id": owner_id,
                "acquired_at": lease.acquired_at,
                "expires_at": lease.expires_at,
                "heartbeat_interval": lease.heartbeat_interval,
                "last_heartbeat": lease.last_heartbeat,
            })
        )
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._lease_heartbeat_loop(lease))
        self._lease_heartbeat_tasks[lease_id] = heartbeat_task
        
        logger.debug("Created lease %s for task %s", lease_id, task_id)
        return lease
        
    async def release_lease(self, lease_id: str) -> bool:
        """Release task lease."""
        # Cancel heartbeat task
        if lease_id in self._lease_heartbeat_tasks:
            self._lease_heartbeat_tasks[lease_id].cancel()
            del self._lease_heartbeat_tasks[lease_id]
            
        # Find and delete lease
        pattern = "leases:*"
        cursor = 0
        while cursor != 0:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                try:
                    data = await self._redis.get(key)
                    if data:
                        lease_info = json.loads(data)
                        if lease_info["lease_id"] == lease_id:
                            await self._redis.delete(key)
                            logger.debug("Released lease %s", lease_id)
                            return True
                except Exception as exc:
                    logger.error("Error releasing lease %s: %s", key, exc)
                    
        return False
        
    async def _lease_heartbeat_loop(self, lease: TaskLease) -> None:
        """Heartbeat loop for task lease."""
        while True:
            try:
                await asyncio.sleep(lease.heartbeat_interval)
                
                if lease.is_expired():
                    break
                    
                # Update heartbeat
                lease.last_heartbeat = time.time()
                
                # Update in Redis
                key = f"leases:{lease.task_id}"
                existing_data = await self._redis.get(key)
                
                if existing_data:
                    lease_info = json.loads(existing_data)
                    if lease_info["owner_id"] == lease.owner_id:
                        lease_info["last_heartbeat"] = lease.last_heartbeat
                        await self._redis.setex(key, 60, json.dumps(lease_info))
                    else:
                        break  # Lease was taken by someone else
                else:
                    break  # Lease no longer exists
                    
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in lease heartbeat %s: %s", lease.lease_id, exc)
                await asyncio.sleep(1.0)
                
    async def get_lease_info(self, task_id: str) -> dict[str, Any] | None:
        """Get information about a task lease."""
        if not self._redis:
            return None
            
        key = f"leases:{task_id}"
        data = await self._redis.get(key)
        
        if data:
            return json.loads(data)
        return None


class CoordinationChannel:
    """Coordination channel for agent communication."""
    
    def __init__(self, channel_id: str, redis_url: str = "redis://localhost:6379"):
        self.channel_id = channel_id
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self.subscribers: set[str] = set()
        self.message_queue: asyncio.Queue = asyncio.Queue()
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Subscribe to channel
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"coordination:{self.channel_id}")
        
        # Start message listener
        asyncio.create_task(self._message_listener(pubsub))
        
        logger.info("Connected to coordination channel %s", self.channel_id)
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _message_listener(self, pubsub) -> None:
        """Listen for coordination messages."""
        while True:
            try:
                message = await pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    await self.message_queue.put(data)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in message listener: %s", exc)
                await asyncio.sleep(1.0)
                
    async def subscribe(self, subscriber_id: str) -> None:
        """Subscribe to coordination channel."""
        self.subscribers.add(subscriber_id)
        
    async def unsubscribe(self, subscriber_id: str) -> None:
        """Unsubscribe from coordination channel."""
        self.subscribers.discard(subscriber_id)
        
    async def publish(self, message: dict[str, Any]) -> None:
        """Publish message to coordination channel."""
        if not self._redis:
            raise RuntimeError("Channel not connected")
            
        await self._redis.publish(
            f"coordination:{self.channel_id}",
            json.dumps(message)
        )
        
    async def receive(self, timeout: float | None = None) -> dict[str, Any] | None:
        """Receive message from coordination channel."""
        try:
            return await asyncio.wait_for(
                self.message_queue.get(),
                timeout=timeout
            )
        except TimeoutError:
            return None


class SynchronizationBarrier:
    """Synchronization barrier for coordinating multiple agents."""
    
    def __init__(self, barrier_id: str, expected_count: int, timeout: float = 30.0):
        self.barrier_id = barrier_id
        self.expected_count = expected_count
        self.timeout = timeout
        self._arrived: set[str] = set()
        self._condition = asyncio.Condition()
        self._completed = False
        
    async def wait(self, agent_id: str) -> bool:
        """Wait at barrier until all agents arrive or timeout."""
        async with self._condition:
            self._arrived.add(agent_id)
            
            # Notify waiting agents
            self._condition.notify_all()
            
            # Wait for all agents or timeout
            start_time = time.time()
            
            while (len(self._arrived) < self.expected_count and 
                   not self._completed and
                   time.time() - start_time < self.timeout):
                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=self.timeout - (time.time() - start_time)
                    )
                except TimeoutError:
                    break
                    
            if len(self._arrived) >= self.expected_count:
                self._completed = True
                self._condition.notify_all()
                return True
            else:
                return False
                
    async def reset(self) -> None:
        """Reset barrier for next use."""
        async with self._condition:
            self._arrived.clear()
            self._completed = False
            self._condition.notify_all()


class DistributedSemaphore:
    """Distributed semaphore for limiting concurrent operations."""
    
    def __init__(self, semaphore_id: str, permits: int, redis_url: str = "redis://localhost:6379"):
        self.semaphore_id = semaphore_id
        self.permits = permits
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._lock_key = f"semaphore:{semaphore_id}:lock"
        
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Initialize semaphore counter only if not exists
        key = f"semaphore:{self.semaphore_id}"
        await self._redis.set(key, self.permits, nx=True)
        
        logger.info("Connected to distributed semaphore %s", self.semaphore_id)
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire permit from distributed semaphore."""
        if not self._redis:
            raise RuntimeError("Semaphore not connected")
            
        start_time = time.time()
        key = f"semaphore:{self.semaphore_id}"
        
        while time.time() - start_time < timeout:
            try:
                # Use WATCH for optimistic locking
                await self._redis.watch(key)
                current_value = await self._redis.get(key)
                
                if current_value is None:
                    await self._redis.unwatch()
                    return False
                    
                current = int(current_value)
                if current <= 0:
                    # No permits available, unwatch and wait
                    await self._redis.unwatch()
                    await asyncio.sleep(0.1)
                    continue
                
                # Decrement atomically
                pipe = self._redis.pipeline()
                pipe.multi()
                pipe.set(key, current - 1)
                await pipe.execute()
                
                return True
                
            except redis.WatchError:
                # Value changed, retry
                await asyncio.sleep(0.05)
                continue
            except Exception as exc:
                logger.error("Error acquiring semaphore: %s", exc)
                return False
                
        return False
        
    async def release(self) -> None:
        """Release permit back to distributed semaphore."""
        if not self._redis:
            raise RuntimeError("Semaphore not connected")
            
        key = f"semaphore:{self.semaphore_id}"
        
        try:
            # Atomic increment
            new_value = await self._redis.incr(key)
            
            if new_value > self.permits:
                # Reset to permits if somehow exceeded
                await self._redis.set(key, self.permits)
                
        except Exception as exc:
            logger.error("Error releasing semaphore: %s", exc)
            
    async def available_permits(self) -> int:
        """Get number of available permits."""
        if not self._redis:
            return 0
            
        try:
            value = await self._redis.get(f"semaphore:{self.semaphore_id}")
            return int(value) if value else 0
        except Exception:
            return 0


# Global coordination instances
consensus_manager: ConsensusManager | None = None
lock_manager: DistributedLockManager | None = None
lease_manager: TaskLeaseManager | None = None