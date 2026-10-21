import type { PrepayModel, Scenario } from "../api";

interface Props {
  index: number;
  color: string;
  scenario: Scenario;
  onChange: (s: Scenario) => void;
}

export function ScenarioEditor({ index, color, scenario, onChange }: Props) {
  const id = `scenario-${index}`;
  return (
    <fieldset className="scenario" style={{ borderTopColor: color }}>
      <legend>Scenario {index + 1}</legend>
      <label htmlFor={`${id}-model`}>Model</label>
      <select
        id={`${id}-model`}
        value={scenario.model}
        onChange={(e) => onChange({ ...scenario, model: e.target.value as PrepayModel })}
      >
        <option value="PSA">PSA</option>
        <option value="CPR">CPR</option>
      </select>
      <label htmlFor={`${id}-speed`}>{scenario.model === "PSA" ? "Speed (% PSA)" : "CPR (%)"}</label>
      <input
        id={`${id}-speed`}
        type="number"
        min={0}
        max={scenario.model === "CPR" ? 100 : 5000}
        step={scenario.model === "PSA" ? 25 : 1}
        value={Number.isNaN(scenario.speed) ? "" : scenario.speed}
        onChange={(e) => onChange({ ...scenario, speed: e.target.valueAsNumber })}
      />
    </fieldset>
  );
}
