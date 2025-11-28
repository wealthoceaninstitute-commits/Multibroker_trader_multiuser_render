"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Signup() {
  const [name, setName] = useState("");
  const [email,setEmail] = useState("");
  const [password,setPassword] = useState("");
  const router = useRouter();

  async function signup() {
    const res = await fetch("https://multibrokertradermultiuser-production-f735.up.railway.app/signup",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name,email,password})
    });

    const data = await res.json();

    if(data.status === "success"){
      alert("✅ User Created Successfully");
      router.push("/login");
    } else {
      alert(data.message);
    }
  }

  return (
    <div style={{
      display:"flex",
      justifyContent:"center",
      alignItems:"center",
      height:"100vh",
      background:"linear-gradient(135deg, #0f172a, #1e3a8a)"
    }}>

      <div style={{
        width:350,
        background:"white",
        padding:30,
        borderRadius:12,
        boxShadow:"0 20px 40px rgba(0,0,0,0.3)",
        textAlign:"center"
      }}>

        <h2 style={{marginBottom:20}}>Create User</h2>

        <input
          style={inputStyle}
          placeholder="Full Name"
          onChange={e=>setName(e.target.value)}
        />

        <input
          style={inputStyle}
          placeholder="Email"
          type="email"
          onChange={e=>setEmail(e.target.value)}
        />

        <input
          style={inputStyle}
          placeholder="Password"
          type="password"
          onChange={e=>setPassword(e.target.value)}
        />

        <button 
          style={btnStyle}
          onClick={signup}
        >
          Create Account
        </button>

        <p
          style={{marginTop:15,cursor:"pointer",color:"#1e40af"}}
          onClick={()=>router.push("/login")}
        >
          Already have account? Login
        </p>

      </div>
    </div>
  );
}

const inputStyle = {
  width:"100%",
  padding:"12px",
  marginBottom:15,
  borderRadius:8,
  border:"1px solid #ccc",
  outline:"none",
  fontSize:14
}

const btnStyle = {
  width:"100%",
  padding:"12px",
  background:"#1e40af",
  color:"white",
  border:"none",
  borderRadius:8,
  cursor:"pointer",
  fontWeight:"bold"
}
