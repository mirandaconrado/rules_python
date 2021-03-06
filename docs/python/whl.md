
<!---
Documentation generated by Skydoc
-->
<h1>Import .whl files into Bazel.</h1>


<nav class="toc">
  <h2>Repository Rules</h2>
  <ul>
    <li><a href="#download_or_build_wheel">download_or_build_wheel</a></li>
    <li><a href="#extract_wheels">extract_wheels</a></li>
  </ul>
</nav>
<a name="download_or_build_wheel"></a>
## download_or_build_wheel

<pre>
download_or_build_wheel(<a href="#download_or_build_wheel.name">name</a>, <a href="#download_or_build_wheel.buildtime_deps">buildtime_deps</a>, <a href="#download_or_build_wheel.pip_args">pip_args</a>, <a href="#download_or_build_wheel.python">python</a>, <a href="#download_or_build_wheel.requirement">requirement</a>, <a href="#download_or_build_wheel.urls">urls</a>, <a href="#download_or_build_wheel.wheel_name">wheel_name</a>)
</pre>




<a name="download_or_build_wheel_args"></a>
### Attributes


<table class="params-table">
  <colgroup>
    <col class="col-param" />
    <col class="col-description" />
  </colgroup>
  <tbody>
    <tr id="download_or_build_wheel.name">
      <td><code>name</code></td>
      <td>
        <p><code><a href="https://bazel.build/docs/build-ref.html#name">Name</a>; Required</code></p>
        <p>A unique name for this rule.</p>
      </td>
    </tr>
    <tr id="download_or_build_wheel.buildtime_deps">
      <td><code>buildtime_deps</code></td>
      <td>
        <p><code>List of <a href="https://bazel.build/docs/build-ref.html#labels">labels</a>; Optional; Default is []</code></p>
        
      </td>
    </tr>
    <tr id="download_or_build_wheel.pip_args">
      <td><code>pip_args</code></td>
      <td>
        <p><code>List of strings; Optional; Default is []</code></p>
        
      </td>
    </tr>
    <tr id="download_or_build_wheel.python">
      <td><code>python</code></td>
      <td>
        <p><code><a href="https://bazel.build/docs/build-ref.html#labels">Label</a>; Optional</code></p>
        
      </td>
    </tr>
    <tr id="download_or_build_wheel.requirement">
      <td><code>requirement</code></td>
      <td>
        <p><code>String; Optional; Default is ''</code></p>
        
      </td>
    </tr>
    <tr id="download_or_build_wheel.urls">
      <td><code>urls</code></td>
      <td>
        <p><code>List of strings; Optional; Default is []</code></p>
        
      </td>
    </tr>
    <tr id="download_or_build_wheel.wheel_name">
      <td><code>wheel_name</code></td>
      <td>
        <p><code>String; Optional; Default is ''</code></p>
        
      </td>
    </tr>
  </tbody>
</table>
<a name="extract_wheels"></a>
## extract_wheels

<pre>
extract_wheels(<a href="#extract_wheels.name">name</a>, <a href="#extract_wheels.additional_runtime_deps">additional_runtime_deps</a>, <a href="#extract_wheels.extras">extras</a>, <a href="#extract_wheels.python">python</a>, <a href="#extract_wheels.remove_runtime_deps">remove_runtime_deps</a>, <a href="#extract_wheels.repository">repository</a>, <a href="#extract_wheels.wheels">wheels</a>)
</pre>

A rule for importing <code>.whl</code> dependencies into Bazel.

<b>This rule is currently used to implement <code>pip_import</code>,
it is not intended to work standalone, and the interface may change.</b>
See <code>pip_import</code> for proper usage.

This rule imports a <code>.whl</code> file as a <code>py_library</code>:
<pre><code>whl_library(
    name = "foo",
    whl = ":my-whl-file",
    repository = "name of pip_import rule",
)
</code></pre>

This rule defines a <code>@foo//:pkg</code> <code>py_library</code> target.


<a name="extract_wheels_args"></a>
### Attributes


<table class="params-table">
  <colgroup>
    <col class="col-param" />
    <col class="col-description" />
  </colgroup>
  <tbody>
    <tr id="extract_wheels.name">
      <td><code>name</code></td>
      <td>
        <p><code><a href="https://bazel.build/docs/build-ref.html#name">Name</a>; Required</code></p>
        <p>A unique name for this rule.</p>
      </td>
    </tr>
    <tr id="extract_wheels.additional_runtime_deps">
      <td><code>additional_runtime_deps</code></td>
      <td>
        <p><code>List of strings; Optional; Default is []</code></p>
        
      </td>
    </tr>
    <tr id="extract_wheels.extras">
      <td><code>extras</code></td>
      <td>
        <p><code>List of strings; Optional; Default is []</code></p>
        <p>A subset of the "extras" available from this &lt;code&gt;.whl&lt;/code&gt; for which
&lt;code&gt;requirements&lt;/code&gt; has the dependencies.</p>
      </td>
    </tr>
    <tr id="extract_wheels.python">
      <td><code>python</code></td>
      <td>
        <p><code><a href="https://bazel.build/docs/build-ref.html#labels">Label</a>; Optional</code></p>
        
      </td>
    </tr>
    <tr id="extract_wheels.remove_runtime_deps">
      <td><code>remove_runtime_deps</code></td>
      <td>
        <p><code>List of strings; Optional; Default is []</code></p>
        
      </td>
    </tr>
    <tr id="extract_wheels.repository">
      <td><code>repository</code></td>
      <td>
        <p><code>String; Optional; Default is ''</code></p>
        
      </td>
    </tr>
    <tr id="extract_wheels.wheels">
      <td><code>wheels</code></td>
      <td>
        <p><code>List of <a href="https://bazel.build/docs/build-ref.html#labels">labels</a>; Optional; Default is []</code></p>
        
      </td>
    </tr>
  </tbody>
</table>
