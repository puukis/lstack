import { Card, CardTitle, Row } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { InstallSection, RuntimeSection } from "@/api/types";

export function StatusCard({
  install,
  runtime,
}: {
  install: InstallSection;
  runtime: RuntimeSection;
}) {
  return (
    <Card>
      <CardTitle>LStack Core</CardTitle>
      <Row label="Claude dir">
        <span className="font-mono truncate">{install.claude_dir}</span>
      </Row>
      <Row label="Version">
        <span className="font-mono">{install.version}</span>
      </Row>
      <Row label="settings.json">
        {install.settings_exists ? (
          install.settings_valid_json ? (
            <Badge variant="pass">valid</Badge>
          ) : (
            <Badge variant="fail">invalid JSON</Badge>
          )
        ) : (
          <Badge variant="fail">missing</Badge>
        )}
      </Row>
      <Row label="OS">{runtime.os}</Row>
      <Row label="Shell">{runtime.shell_mode}</Row>
      <Row label="Python">
        {runtime.python_available ? (
          <Badge variant="pass">
            {runtime.python_provider} {runtime.python_version}
          </Badge>
        ) : (
          <Badge variant="fail">missing</Badge>
        )}
      </Row>
      <Row label="Git">
        {runtime.git_available ? (
          <Badge variant="pass">available</Badge>
        ) : (
          <Badge variant="fail">missing</Badge>
        )}
      </Row>
      <Row label="Path rule">
        <span className="font-mono">{runtime.path_rule}</span>
      </Row>
    </Card>
  );
}
