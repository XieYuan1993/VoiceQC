export interface SupervisorContact { name: string; email_enabled: boolean; email: string; sms_enabled: boolean; phone: string }
export const emptySupervisor: SupervisorContact = { name: "", email_enabled: false, email: "", sms_enabled: false, phone: "" };
export function complaintTrigger(text: string): string | null {
  const phrases = ["我要投訴", "我要投诉", "要投訴", "要投诉", "投訴你", "投诉你", "投訴佢", "向電視", "向电视", "搵你主管", "搵個主管", "搵個經理", "找你主管", "找你們主管", "找你们主管", "要求主管", "主管接聽", "主管接听", "服務咁差", "服务咁差", "服務好差", "非常不滿", "非常不满", "非常的不滿", "非常的不满", "非常不高興", "非常不高兴", "非常的不高興", "非常的不高兴"];
  const value = text.replace(/\s+/g, "");
  if (/(不會|不会|唔會|不想|唔想|不要|毋須)(再)?投[訴诉]/.test(value)) return null;
  return phrases.find((phrase) => value.includes(phrase)) ?? null;
}
