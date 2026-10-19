import React,{useEffect,useState} from 'react';
export function navigate(path){if(location.pathname!==path){history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'));window.scrollTo({top:0,behavior:'instant'})}}
export function Link({to,children,onClick,...props}){return <a href={to} {...props} onClick={e=>{onClick?.(e);if(!e.defaultPrevented&&e.button===0&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey){e.preventDefault();navigate(to)}}}>{children}</a>}
export function usePath(){const [path,setPath]=useState(location.pathname);useEffect(()=>{const fn=()=>setPath(location.pathname);addEventListener('popstate',fn);return()=>removeEventListener('popstate',fn)},[]);return path}
