"use strict";
(async()=>{
  const response=await fetch('/api/v1/setup-status');
  if(!(await response.json()).initialized){
    const form=document.getElementById('login-form');
    const note=document.createElement('p');note.textContent='First use: choose an operator password of at least 16 characters. It also unlocks this machine’s encrypted agent identity. Keep it in your password manager.';form.before(note);
    const confirmation=document.createElement('input');confirmation.type='password';confirmation.autocomplete='new-password';confirmation.required=true;confirmation.minLength=16;confirmation.id='confirm-password';
    const label=document.createElement('label');label.textContent='Confirm new password';label.append(confirmation);form.insertBefore(label,form.querySelector('button'));
    document.getElementById('password').autocomplete='new-password';document.getElementById('password').minLength=16;
    form.querySelector('button').textContent='Create owner & unlock';
    const normalLogin=form.onsubmit;
    form.onsubmit=async(event)=>{event.preventDefault();const password=document.getElementById('password').value;if(password!==confirmation.value){document.getElementById('message').textContent='Passwords do not match.';return;}const saved=await fetch('/api/v1/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});if(!saved.ok){document.getElementById('message').textContent=(await saved.json()).detail;return;}confirmation.value='';label.remove();note.remove();form.onsubmit=normalLogin;await normalLogin(event);};
  }
})();
