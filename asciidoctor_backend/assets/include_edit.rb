# frozen_string_literal: true
require 'asciidoctor'
require 'pathname'
require 'set'

Asciidoctor::Extensions.register do
  # Ensure sourcemap so section.source_location is populated
  preprocessor do
    process do |doc, _reader|
      doc.sourcemap = true
      nil
    end
  end

  treeprocessor do
    process do |doc|
      edit_base = (doc.attr 'edit-base') || ''
      return nil if edit_base.empty?

      repo_root = File.expand_path((doc.attr 'repo-root') || Dir.pwd)
      docfile   = File.expand_path((doc.attr 'docfile') || '')
      root_path = Pathname.new(repo_root)

      seen = Set.new

      (doc.find_by context: :section).each do |sect|
        sl = sect.source_location
        next unless sl

        # Prefer absolute path; fall back to dir+file; finally file name
        src = sl.path || (sl.file && sl.dir ? File.join(sl.dir, sl.file) : sl.file)
        next unless src
        src = File.expand_path(src)

        # Skip sections from the page's own file; we only tag included files
        next if src == docfile

        # Compute repo-relative path for edit URL
        rel =
          begin
            Pathname.new(src).relative_path_from(root_path).to_s
          rescue
            File.basename(src)
          end

        next if seen.include?(rel)
        seen << rel

        marker = %(<span class="adoc-include-edit" data-edit="#{edit_base}#{rel}"></span>)
        sect.blocks.unshift create_block(sect, :pass, marker, {})
      end

      nil
    end
  end
end
