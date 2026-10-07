"""P1 fix: when autonomous=True and tools succeed, the final answer must be
the real answer, not audit text.

The defect (audit 2026-08-16, P1): the completion-audit pass could emit
tokens that replaced the real answer because the agent loop did not preserve
``pending_final_answer`` before the audit began.
"""

from __future__ import annotations

from backend.agents.base import AgentBase


class TestP1AnswerNotDiscarded:
    def test_audit_noop_keeps_pending_answer(self) -> None:
        """When the audit produces only a noop verdict, the pending answer
        must survive as the final answer."""
        base = AgentBase.__new__(AgentBase)
        base.name = "NEXUS"
        base.supported_actions = ("read_file", "write_file")

        pending = "The real answer."
        audit = "tudo verificado; nothing to do"
        reconciled = AgentBase._reconcile_audited_answer(
            audit,
            pending,
            audited_with_new_evidence=False,
        )
        assert reconciled == pending

    def test_audit_with_new_evidence_supersedes(self) -> None:
        """When the audit executes further tools, its answer supersedes."""
        base = AgentBase.__new__(AgentBase)
        base.name = "NEXUS"
        base.supported_actions = ("read_file",)

        pending = "Initial answer."
        audit = "Updated answer after running tests."
        reconciled = AgentBase._reconcile_audited_answer(
            audit,
            pending,
            audited_with_new_evidence=True,
        )
        assert reconciled == audit

    def test_empty_pending_returns_audit(self) -> None:
        """When there is no pending answer, audit answer is used."""
        base = AgentBase.__new__(AgentBase)
        base.name = "NEXUS"
        base.supported_actions = ()

        pending = ""
        audit = "Audit-only answer."
        reconciled = AgentBase._reconcile_audited_answer(
            audit,
            pending,
            audited_with_new_evidence=False,
        )
        assert reconciled == audit

    def test_substantive_audit_appended_without_new_evidence(self) -> None:
        """When the audit adds real substance but no new tool evidence, both
        the pending answer and the audit must be preserved (pending first)."""
        base = AgentBase.__new__(AgentBase)
        base.name = "NEXUS"
        base.supported_actions = ("read_file", "write_file")

        pending = (
            "Encontrei o bug: em list_page o offset esta errado. "
            "Corrigi para (page - 1) * size."
        )
        audit = (
            "A auditoria confirmou que a correcao esta correta e nao "
            "introduziu regressoes. Alem disso, o mesmo padrao aparece em "
            "list_archive; recomendo aplicar a mesma correcao la."
        )
        reconciled = AgentBase._reconcile_audited_answer(
            audit,
            pending,
            audited_with_new_evidence=False,
        )
        assert pending in reconciled
        assert audit in reconciled
        assert reconciled.startswith(pending)

    def test_long_audit_without_noop_markers_appended(self) -> None:
        """A long audit text (>400 chars) without noop markers must be appended
        to the pending answer, not replace it."""
        base = AgentBase.__new__(AgentBase)
        base.name = "NEXUS"
        base.supported_actions = ("read_file",)

        pending = "A resposta real do utilizador."
        audit = (
            "A auditoria examinou os ficheiros modificados e encontrou "
            "um segundo problema: o tratamento de erros em api_client.py "
            "nao captura TimeoutError, o que significa que uma requisicao "
            "lenta deixa a conexao aberta indefinidamente. E necessario "
            "adicionar um try/except com fechamento de sessao no finally."
        )
        reconciled = AgentBase._reconcile_audited_answer(
            audit,
            pending,
            audited_with_new_evidence=False,
        )
        assert reconciled.startswith(pending)
        assert audit in reconciled
