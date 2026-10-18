import React from 'react';
import {Globe2} from 'lucide-react';
import {useLocale,setLanguage} from '../i18n';
export default function LanguageSwitcher(){
 const language=useLocale();
 return <label className="language-switcher"><Globe2 size={15} aria-hidden="true"/><select aria-label="Язык / Тіл / Language" value={language} onChange={event=>setLanguage(event.target.value)}><option value="ru">RU</option><option value="kk">ҚАЗ</option><option value="en">EN</option></select></label>;
}
