import { Panel } from "@/components/ui/panel";

export default function HelpPage() {
  return (
    <Panel title="Help" kicker="Guide">
      <article className="mm-help">
        <h3>Running MarketMesh</h3>
        <p>
          Run <code>make setup</code> then <code>make dev</code>. Open
          http://127.0.0.1:3000, click <strong>Run sample brief</strong>, inspect the
          seller lanes and the A2A wire, then approve the recommended award.
        </p>

        <h3>Sample brief</h3>
        <p>
          &ldquo;Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery
          within 14 days, 24-month warranty, 30-day returns. Prefer a
          sustainability-certified seller.&rdquo;
        </p>

        <h3>Glossary</h3>
        <ul>
          <li>
            <strong>Agent Card</strong> — a JSON document describing an agent&apos;s
            skills, transports, and auth, served at{" "}
            <code>/.well-known/agent-card.json</code>.
          </li>
          <li>
            <strong>Task</strong> — a stateful unit of work between agents with
            status, artifacts, and streaming updates.
          </li>
          <li>
            <strong>Artifact</strong> — a named output (offer, order, commerce-error)
            attached to a task.
          </li>
          <li>
            <strong>DataPart</strong> — a structured JSON payload inside an A2A
            message, carrying the commerce envelope.
          </li>
          <li>
            <strong>Interrupt</strong> — a LangGraph pause that requires a human
            decision before the buyer places an order.
          </li>
        </ul>
      </article>
    </Panel>
  );
}
