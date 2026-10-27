package aiconsole

import "encoding/json"

const responseInstructions = "You are KIKI OS assistant. Answer the user's request, not a summary or repetition of it. Output one JSON object. First choose kind: plan for a request to inspect or change this system; message for conversation or general explanation. Include kind before schema. Use English ASCII values (legacy field names end in _ko).\n" +
	"For greetings and explanation questions, answer directly with schema kiki-ai-message-v1 and reply containing your actual answer, not a restatement of the question. Do not include commands. Example for Hello: {\"kind\":\"message\",\"schema\":\"kiki-ai-message-v1\",\"reply\":\"Hello! I can help with KIKI OS networking, disks, services and packages. What would you like to do?\"}\n" +
	"For system inspection or change requests, produce schema kiki-ai-command-plan-v1 with exact argv commands for the user to review. Example for Show kernel version: {\"kind\":\"plan\",\"schema\":\"kiki-ai-command-plan-v1\",\"summary_ko\":\"Check the running kernel version\",\"risk\":\"low\",\"impact_ko\":\"Read-only. No system changes.\",\"commands\":[{\"description_ko\":\"Read kernel version\",\"argv\":[\"uname\",\"-r\"]}],\"verification\":[],\"rollback\":[],\"confirmation_ko\":\"Run this read-only command?\"}\n" +
	"Questions about your capabilities, such as What can you help me with?, are ALWAYS kind message. Answer with your capabilities, not a kernel command. General technical questions and greetings are also message. Only use plan for a specific requested inspection or change. Examples are format examples, not tasks to carry out. Never copy an example task unless the user asked for it.\n" +
	"Never claim commands ran or changes succeeded. Execution requires separate user approval. Do not guess devices or addresses; use inventory only as data. If required information is missing, ask a question using the message schema. Include connection checks and rollback for network changes. Never invent commands for conversation."

// Keep kind first: llama.cpp grammar generation follows property order.
// Go maps would sort commands before kind and bias generation into the other branch.
// Go validation remains mandatory even when an endpoint ignores the grammar.
func responseSchema() json.RawMessage {
	return json.RawMessage(`{
  "anyOf": [
    {
      "type": "object",
      "properties": {
        "kind": {
          "const": "message"
        },
        "schema": {
          "const": "kiki-ai-message-v1"
        },
        "reply": {
          "type": "string"
        }
      },
      "required": [
        "kind",
        "schema",
        "reply"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "kind": {
          "const": "plan"
        },
        "schema": {
          "const": "kiki-ai-command-plan-v1"
        },
        "summary_ko": {
          "type": "string"
        },
        "risk": {
          "enum": [
            "low",
            "normal",
            "network",
            "storage",
            "system",
            "critical"
          ]
        },
        "impact_ko": {
          "type": "string"
        },
        "commands": {
          "$ref": "#/$defs/commands"
        },
        "verification": {
          "$ref": "#/$defs/checks"
        },
        "rollback": {
          "$ref": "#/$defs/checks"
        },
        "confirmation_ko": {
          "type": "string"
        }
      },
      "required": [
        "kind",
        "schema",
        "summary_ko",
        "risk",
        "impact_ko",
        "commands",
        "verification",
        "rollback",
        "confirmation_ko"
      ],
      "additionalProperties": false
    }
  ],
  "$defs": {
    "command": {
      "type": "object",
      "properties": {
        "description_ko": {
          "type": "string"
        },
        "argv": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "maxItems": 128
        },
        "directory": {
          "type": "string"
        },
        "environment": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
        "timeout_seconds": {
          "type": "integer",
          "minimum": 0,
          "maximum": 3600
        }
      },
      "required": [
        "description_ko",
        "argv"
      ],
      "additionalProperties": false
    },
    "commands": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/command"
      },
      "minItems": 1,
      "maxItems": 32
    },
    "checks": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/command"
      },
      "maxItems": 16
    }
  }
}`)
}
