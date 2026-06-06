"use client";

import { useState } from "react";
import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";

export function CopilotDemo() {
  const [missionStatus, setMissionStatus] = useState(
    "Idle - waiting for a creative brief",
  );

  useCopilotReadable({
    description: "The current REZN Conductor mission status shown to the operator",
    value: missionStatus,
  });

  useCopilotAction({
    name: "setMissionStatus",
    description: "Update the REZN Conductor mission status banner.",
    parameters: [
      {
        name: "status",
        type: "string",
        description: "A short, human-readable status message to display.",
        required: true,
      },
    ],
    handler: ({ status }) => {
      setMissionStatus(status);
    },
  });

  return (
    <>
      <p className="text-sm text-zinc-500">
        Agent status:{" "}
        <span className="text-zinc-300">{missionStatus}</span>
      </p>

      <CopilotPopup
        labels={{
          title: "REZN Conductor",
          initial:
            'Try: "set the mission status to rendering candidates".',
        }}
      />
    </>
  );
}
