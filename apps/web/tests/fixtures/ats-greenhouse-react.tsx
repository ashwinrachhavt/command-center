import { useState } from "react";
import { createRoot } from "react-dom/client";

/* eslint-disable jsx-a11y/role-has-required-aria-props -- The audited Greenhouse react-select options omit aria-selected and expose selection through select__option--is-selected. */

type Choice = {
  id: string;
  label: string;
  disabled?: boolean;
};

const validChoices: Choice[] = [
  { id: "country-ca", label: "Canada" },
  { id: "country-us", label: "United States" },
  { id: "country-disabled", label: "Unavailable region", disabled: true },
];

const duplicateChoices: Choice[] = [
  { id: "work-mode-remote-1", label: "Remote" },
  { id: "work-mode-remote-2", label: "Remote" },
];

function GreenhouseSelect({ duplicate }: { duplicate: boolean }) {
  const [choices, setChoices] = useState(
    duplicate ? duplicateChoices : validChoices,
  );
  const [headline, setHeadline] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [selected, setSelected] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const listboxId = "country-listbox";

  return (
    <main>
      <h1>Greenhouse-shaped React application</h1>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(true);
        }}
      >
        <label id="country-label">Country</label>
        <div className="select__container">
          <div className="select__control">
            {selected ? (
              <div className="select__single-value">{selected}</div>
            ) : null}
            <input
              aria-autocomplete="list"
              aria-controls={menuOpen ? listboxId : undefined}
              aria-expanded={menuOpen}
              aria-haspopup="listbox"
              aria-labelledby="country-label"
              className="select__input"
              onChange={() => undefined}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setMenuOpen(true);
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setMenuOpen(false);
                }
              }}
              role="combobox"
              type="text"
              value=""
            />
          </div>
          {menuOpen ? (
            <div
              aria-multiselectable="false"
              className="select__menu"
              id={listboxId}
              role="listbox"
            >
              {choices.map((choice) => (
                <div
                  aria-disabled={choice.disabled ? "true" : "false"}
                  className={`select__option${
                    selected === choice.label
                      ? " select__option--is-selected"
                      : ""
                  }`}
                  id={choice.id}
                  key={choice.id}
                  onClick={() => {
                    if (choice.disabled) return;
                    setSelected(choice.label);
                    setMenuOpen(false);
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                  role="option"
                >
                  {choice.label}
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <label htmlFor="headline">Professional headline</label>
        <input
          id="headline"
          name="headline"
          onChange={(event) => setHeadline(event.currentTarget.value)}
          type="text"
          value={headline}
        />

        <button
          id="drift-options"
          onClick={() =>
            setChoices((current) =>
              current.filter((choice) => choice.id !== "country-ca"),
            )
          }
          type="button"
        >
          Change available options
        </button>
        <button type="submit">Submit application</button>
      </form>
      <output id="greenhouse-state">
        {JSON.stringify({ selected, headline, submitted })}
      </output>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing synthetic Greenhouse fixture root");
createRoot(root).render(
  <GreenhouseSelect duplicate={root.dataset.mode === "duplicate"} />,
);
