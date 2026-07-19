import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const robotWalk = defineTool({
	name: "robot_walk",
	label: "Robot Walk",
	description: "控制机器人移动方向和持续时间。vx 前后速度，vy 左右速度，vyaw 转向速度，duration_sec 持续时间。",
	promptSnippet: "robot_walk(vx, vy, vyaw, duration_sec): request robot locomotion through voice_bridge.",
	promptGuidelines: ["Use robot_walk only for explicit movement requests."],
	executionMode: "sequential",
	parameters: Type.Object({
		vx: Type.Number({ minimum: -1, maximum: 1, description: "Forward velocity. Positive moves forward." }),
		vy: Type.Number({ minimum: -1, maximum: 1, description: "Lateral velocity. Positive moves left." }),
		vyaw: Type.Number({ minimum: -1, maximum: 1, description: "Yaw velocity. Positive turns left." }),
		duration_sec: Type.Number({ minimum: 0.1, maximum: 10, description: "Movement duration in seconds." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_walk accepted ${JSON.stringify(params)}` }],
			details: params,
		};
	},
});

const robotStop = defineTool({
	name: "robot_stop",
	label: "Robot Stop",
	description: "立即停止机器人运动。",
	promptSnippet: "robot_stop(): request an immediate stop through voice_bridge.",
	promptGuidelines: ["Use robot_stop for stop, cancel, freeze, or unsafe movement requests."],
	executionMode: "sequential",
	parameters: Type.Object({}),
	async execute() {
		return {
			content: [{ type: "text", text: "robot_stop accepted" }],
			details: {},
		};
	},
});

const robotTextMotion = defineTool({
	name: "robot_text_motion",
	label: "Robot Text Motion",
	description:
		"使用 TextOp 文本动作模型控制机器人。prompt 必须是简短、简单、单一动作的英文指令，例如 walk、turn right、wave；时间只放在 duration_sec。新指令会在动作片段边界替换当前指令。",
	promptSnippet:
		"robot_text_motion(prompt, duration_sec): stream one short simple English TextOp motion command through voice_bridge.",
	promptGuidelines: [
		"Use only when Robot context motion_backend is textop.",
		"Translate the requested physical motion into a short simple English command such as 'walk', 'turn right', or 'wave'.",
		"Use one action per prompt. Do not use Chinese, explanations, multi-step sequences, scene descriptions, or abstract intent.",
		"Put time only in duration_sec; do not include duration words or numbers in prompt.",
	],
	executionMode: "sequential",
	parameters: Type.Object({
		prompt: Type.String({
			minLength: 1,
			maxLength: 100,
			description: "One short simple English physical-action command, for example: walk, turn right, wave.",
		}),
		duration_sec: Type.Number({ minimum: 0.16, maximum: 30, description: "Maximum prompt duration in seconds." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_text_motion accepted ${JSON.stringify(params)}` }],
			details: params,
		};
	},
});

const robotSay = defineTool({
	name: "robot_say",
	label: "Robot Say",
	description: "通过 TTS 输出语音。",
	promptSnippet: "robot_say(text): request text-to-speech through voice_bridge.",
	parameters: Type.Object({
		text: Type.String({ minLength: 1, description: "Text to speak." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_say accepted ${params.text}` }],
			details: params,
		};
	},
});

const robotLed = defineTool({
	name: "robot_led",
	label: "Robot LED",
	description: "控制 LED 颜色和持续时间。",
	promptSnippet: "robot_led(r, g, b, ttl_sec): request LED color through voice_bridge.",
	parameters: Type.Object({
		r: Type.Number({ minimum: 0, maximum: 255, description: "Red channel." }),
		g: Type.Number({ minimum: 0, maximum: 255, description: "Green channel." }),
		b: Type.Number({ minimum: 0, maximum: 255, description: "Blue channel." }),
		ttl_sec: Type.Number({ minimum: 0.1, maximum: 30, description: "LED duration in seconds." }),
	}),
	async execute(_toolCallId, params) {
		return {
			content: [{ type: "text", text: `robot_led accepted ${JSON.stringify(params)}` }],
			details: params,
		};
	},
});

export default function (pi: ExtensionAPI) {
	pi.registerTool(robotWalk);
	pi.registerTool(robotTextMotion);
	pi.registerTool(robotStop);
	pi.registerTool(robotSay);
	pi.registerTool(robotLed);
}
