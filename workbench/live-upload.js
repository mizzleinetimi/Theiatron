/* Cancellable two-phase local upload. Reserving never starts inference; only a
   complete, admitted transfer does. Dependency injection keeps race tests small. */
(function(root) {
  "use strict";
  class LiveUpload {
    constructor({write,token,onProgress=()=>{},XHR=XMLHttpRequest}) {
      Object.assign(this,{write,token,onProgress,XHR});
      this.cancelled=false;this.id=null;this.xhr=null;
    }
    async start(file,settings) {
      if (!file || file.size<=0 || file.size>4*1024**3) throw Error("Choose a nonempty video up to 4 GB");
      const job=await this.write('/api/live/uploads',{filename:file.name,size_bytes:file.size,...settings});
      this.id=job.id;
      if(this.cancelled) {
        await this.write(`/api/live/uploads/${this.id}/cancel`,{});
        throw Error("Upload cancelled");
      }
      const result=await new Promise((resolve,reject)=>{
        const xhr=this.xhr=new this.XHR();
        xhr.open('POST',`/api/live/uploads/${this.id}/content`);
        xhr.setRequestHeader('X-Theiatron-Token',this.token);
        xhr.timeout=610000;
        xhr.upload.onprogress=(e)=>this.onProgress(e.loaded,e.total || file.size);
        xhr.onerror=()=>reject(Error("Upload connection lost. Check the live session before retrying."));
        xhr.ontimeout=()=>reject(Error("Upload timed out. Check the live session before retrying."));
        xhr.onabort=()=>reject(Error("Upload cancelled"));
        xhr.onload=()=>{
          try {
            const body=JSON.parse(xhr.responseText);
            if(xhr.status<200 || xhr.status>=300) throw Error(body.error || `Upload failed (${xhr.status})`);
            resolve(body);
          } catch(e) {reject(e);}
        };
        xhr.send(file);
      });
      if(this.cancelled) throw Error("Upload cancelled");
      return result;
    }
    async cancel() {
      this.cancelled=true;
      this.xhr?.abort();
      // If transfer finished just before cancellation, the server also stops
      // detection for this source only. It cannot stop another source/session.
      if(this.id) return this.write(`/api/live/uploads/${this.id}/cancel`,{});
      return null;
    }
  }
  if(typeof module!=="undefined")module.exports={LiveUpload};
  else root.LiveUpload=LiveUpload;
})(typeof window!=="undefined"?window:globalThis);
