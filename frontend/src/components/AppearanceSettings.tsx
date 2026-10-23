"use client";

import { useId } from "react";

import { SettingsSection } from "@/components/app/SettingsSection";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/i18n";

const t = copy.settings.appearance;

/**
 * 设置「外观」：备用头像记在这台设备上、按用户分开；没有配置资源时禁用并说明。
 * 值由导航外壳持有，一拨开关，登录后应用里的头像和一级「外观」的摘要都马上跟着换。
 */
export function AppearanceSettings() {
  const { account, characters, appearance, changeAppearance } = useDirectory();
  const id = useId();
  const hasAlternate = characters?.some((character) => character.scsp_avatar_url) ?? false;

  if (!account) return null;

  return (
    <SettingsSection>
      <FieldGroup>
        <Field orientation="horizontal" data-disabled={!hasAlternate || undefined}>
          <FieldContent>
            <FieldLabel htmlFor={`${id}-scsp`}>{t.scspAvatars}</FieldLabel>
            {!hasAlternate && <FieldDescription id={`${id}-hint`}>{t.noAlternate}</FieldDescription>}
          </FieldContent>
          <Switch
            id={`${id}-scsp`}
            disabled={!hasAlternate}
            aria-describedby={!hasAlternate ? `${id}-hint` : undefined}
            checked={appearance.scspAvatars}
            onCheckedChange={(scspAvatars) => changeAppearance({ ...appearance, scspAvatars })}
          />
        </Field>
      </FieldGroup>
    </SettingsSection>
  );
}
