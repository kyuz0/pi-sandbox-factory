import slack from './node_modules/@dreki-gg/pi-slack/extensions/slack/index.ts';

export default function (pi) {
  process.env.SLACK_CREDENTIALS_FILE = '/home/node/.pi/agent/communications/slack.json';
  return slack(pi);
}
