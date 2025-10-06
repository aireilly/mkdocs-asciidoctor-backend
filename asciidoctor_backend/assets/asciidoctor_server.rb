#!/usr/bin/env ruby
# frozen_string_literal: true

require 'asciidoctor'
require 'json'
require 'socket'

# Long-running AsciiDoctor backend server that processes conversion requests via a Unix socket
class AsciidoctorServer
  # Maximum number of concurrent worker threads
  MAX_WORKERS = 16

  def initialize(socket_path)
    @socket_path = socket_path
    @server = nil
    @queue = Queue.new
    @workers = []
  end

  def start
    # Clean up existing socket
    File.unlink(@socket_path) if File.exist?(@socket_path)

    @server = UNIXServer.new(@socket_path)
    puts "AsciiDoctor server started on #{@socket_path}"

    # Graceful shutdown
    trap('INT') { shutdown }
    trap('TERM') { shutdown }

    # Start worker thread pool
    start_workers

    # Accept connections and queue them for workers
    loop do
      begin
        client = @server.accept
        @queue << client
      rescue StandardError => e
        warn "Error accepting client: #{e.message}"
        warn e.backtrace.join("\n")
      end
    end
  end

  def start_workers
    MAX_WORKERS.times do
      @workers << Thread.new do
        loop do
          begin
            client = @queue.pop
            handle_client(client)
          rescue StandardError => e
            warn "Error handling client: #{e.message}"
            warn e.backtrace.join("\n")
          end
        end
      end
    end
  end

  def handle_client(client)
    # Read request length (4 bytes, big-endian)
    length_bytes = client.read(4)
    return unless length_bytes

    length = length_bytes.unpack1('N')

    # Read request JSON
    request_json = client.read(length)
    request = JSON.parse(request_json)

    # Process the conversion
    response = process_request(request)

    # Send response
    response_json = JSON.dump(response)
    client.write([response_json.bytesize].pack('N'))
    client.write(response_json)
  ensure
    client&.close
  end

  def process_request(request)
    case request['action']
    when 'convert'
      convert_document(request)
    when 'ping'
      { status: 'ok', message: 'pong' }
    when 'shutdown'
      Thread.new { sleep 0.1; shutdown }
      { status: 'ok', message: 'shutting down' }
    else
      { status: 'error', message: "Unknown action: #{request['action']}" }
    end
  rescue StandardError => e
    { status: 'error', message: e.message, backtrace: e.backtrace }
  end

  def convert_document(request)
    file_path = request['file_path']
    options = build_options(request['options'] || {})

    # Load and convert the document once
    doc = Asciidoctor.load_file(file_path, options)
    html = doc.convert

    {
      status: 'ok',
      html: html,
      title: doc.doctitle,
      attributes: doc.attributes
    }
  rescue StandardError => e
    {
      status: 'error',
      message: e.message,
      backtrace: e.backtrace
    }
  end

  def build_options(opts)
    options = {
      safe: :safe,
      backend: 'html5',
      standalone: false,
      to_file: false
    }

    # Map common options
    options[:safe] = opts['safe_mode'].to_sym if opts['safe_mode']
    options[:base_dir] = opts['base_dir'] if opts['base_dir']
    options[:attributes] = opts['attributes'] if opts['attributes']
    options[:requires] = opts['requires'] if opts['requires']

    # Load required libraries
    if opts['requires']
      opts['requires'].each { |req| require req }
    end

    options
  end

  def shutdown
    puts "\nShutting down server..."
    @server&.close
    File.unlink(@socket_path) if File.exist?(@socket_path)
    exit(0)
  end
end

# Start the server
if __FILE__ == $PROGRAM_NAME
  socket_path = ARGV[0] || '/tmp/asciidoctor.sock'
  server = AsciidoctorServer.new(socket_path)
  server.start
end
