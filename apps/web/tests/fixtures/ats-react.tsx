import { useState } from "react";
import { createRoot } from "react-dom/client";

type ApplicationState = {
  name: string;
  workMode: string;
  relocate: boolean;
  autofillFilename: string;
  resumeFilename: string;
  submitted: boolean;
};

const initialState: ApplicationState = {
  name: "",
  workMode: "",
  relocate: false,
  autofillFilename: "",
  resumeFilename: "",
  submitted: false,
};

function SyntheticAshbyApplication() {
  const [state, setState] = useState(initialState);
  const update = (values: Partial<ApplicationState>) =>
    setState((current) => ({ ...current, ...values }));

  return (
    <main>
      <h1>Ashby-shaped React application</h1>
      <form
        id="ashby-form"
        onSubmit={(event) => {
          event.preventDefault();
          update({ submitted: true });
        }}
      >
        <label htmlFor="candidate-name">Full name</label>
        <input
          id="candidate-name"
          name="_systemfield_name"
          onChange={(event) => update({ name: event.currentTarget.value })}
          type="text"
          value={state.name}
        />

        <fieldset>
          <legend>Preferred work arrangement</legend>
          {[
            ["remote", "Remote"],
            ["hybrid", "Hybrid"],
          ].map(([value, label]) => (
            <label key={value}>
              <input
                checked={state.workMode === value}
                name="work_mode"
                onChange={(event) =>
                  event.currentTarget.checked && update({ workMode: value })
                }
                type="radio"
                value={value}
              />
              {label}
            </label>
          ))}
        </fieldset>

        <label>
          <input
            checked={state.relocate}
            id="relocate"
            name="relocate"
            onChange={(event) =>
              update({ relocate: event.currentTarget.checked })
            }
            type="checkbox"
          />
          Open to relocation
        </label>

        <label htmlFor="autofill-resume">Autofill from resume</label>
        <input
          accept=".pdf,application/pdf"
          id="autofill-resume"
          onChange={(event) =>
            update({
              autofillFilename: event.currentTarget.files?.[0]?.name ?? "",
            })
          }
          type="file"
        />

        <label htmlFor="actual-resume">Resume</label>
        <input
          accept=".pdf,application/pdf"
          id="actual-resume"
          name="_systemfield_resume"
          onChange={(event) =>
            update({
              resumeFilename: event.currentTarget.files?.[0]?.name ?? "",
            })
          }
          type="file"
        />

        <button type="submit">Submit Application</button>
      </form>
      <output id="react-state">{JSON.stringify(state)}</output>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing synthetic React fixture root");
createRoot(root).render(<SyntheticAshbyApplication />);
